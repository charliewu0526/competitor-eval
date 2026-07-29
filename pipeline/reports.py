"""MR-A (#55): User Report 状态机的策略层 (PRD #54 / ADR-0020~0023).

厚地基票: 一次性把 User Report 的状态机定死, 让后续 B/C/C2/D 谁都不再改状态机
定义、不再动 schema, 只往已存在的状态/字段里填行为
(prefactor: make the change easy, then make the easy change)。

store.set_user_report_status 什么状态都肯写 (纯落地原语); 本模块在其上补「策略」:
合法流转守卫 —— 拦住非法跳转 (submitted 不能倒回、终态 closed 不能再流转、
三分叉只能从 ai-working 出去等), 让状态机单向可控。分工与 assignments.py 完全一致
(store 落地 / 此层守卫)。

状态机 (CONTEXT v4「反馈状态机」):
    submitted -> queued -> ai-working -> 三分叉
        patch-ready (低危区产出 diff+冒烟过, 等 owner 审)
        needs-human (碰硬禁区或 AI 判断改不了, 转人工附诊断)
        ai-failed   (试了但测试没过)
    owner 审 (仅 patch-ready 可审): 批准 -> 冒烟金丝雀 -> resolved。
        关键: report 在金丝雀跑通前一直停在 patch-ready; 金丝雀 (D) 过了才 resolve()
        置 resolved (故 resolved = 已上线的成功终态)。金丝雀失败的自动回滚不是从
        resolved 退回, 而是仍在 patch-ready 时走 patch-ready -> needs-human ——
        与 owner 主动拒绝共用同一条边。因此 resolved 无需回到 needs-human,
        _ALLOWED 表对 D 已完备, MR-D 不必再改状态机。
        拒绝 -> needs-human (可留言让 AI 重试一次)
    重试回路: needs-human -> queued (owner 让 AI 再试一次, 重新入 cron 队列)
    终态 closed (通知提交者), 从 resolved / needs-human / ai-failed 收口。

ADR-0020: User Report 与 Finding 是两张独立表、两条流, 互不引用 —— 本模块只碰
user_report, 从不 import findings。

本票边界: 能以编程方式 create 一条 report、驱动它合法流转、非法转移被拒。
还没有 UI (MR-B)、没有提交端点 (MR-B)、没有 repair agent (MR-C)、没有金丝雀 (MR-D)。
"""
from __future__ import annotations

import time
import uuid

from pipeline import store


# --- 状态机: 合法流转表 ----------------------------------------------------
# submitted   : 刚提交, 待入队。
# queued      : 已入队, 待 cron 扫 (松耦合, 后端不同步调 AI)。
# ai-working  : 修复 Agent 正在隔离 worktree 上干活。
# patch-ready : 低危区产出 diff + 冒烟过, 等 owner 审 (唯一可被 owner 审的态)。
# needs-human : 碰硬禁区/AI 改不了/owner 拒绝, 转人工。
# ai-failed   : AI 试了但测试没过。
# resolved    : owner 批准且金丝雀过, 修复上线。
# closed      : 终态, 通知提交者。
STATES = (
    "submitted", "queued", "ai-working", "patch-ready",
    "needs-human", "ai-failed", "resolved", "closed",
)

# 允许的 status -> 下一 status 集合。未知/终态 -> 空集 (fail closed)。
_ALLOWED: dict[str, frozenset[str]] = {
    "submitted":   frozenset({"queued"}),
    "queued":      frozenset({"ai-working"}),
    # 三分叉: Agent 干完只能落到这三态之一。
    "ai-working":  frozenset({"patch-ready", "needs-human", "ai-failed"}),
    # owner 审: 批准 -> resolved; 拒绝 -> needs-human。
    "patch-ready": frozenset({"resolved", "needs-human"}),
    # 转人工后: owner 可让 AI 重试 (回 queued 重新入 cron 队列), 或直接收口 closed。
    # 金丝雀失败也退回这里 (D), 故 needs-human 是可重试/可收口的枢纽态。
    "needs-human": frozenset({"queued", "closed"}),
    # AI 试败: owner 可让它再排队重试, 或直接收口。
    "ai-failed":   frozenset({"queued", "closed"}),
    # 修复上线后收口。
    "resolved":    frozenset({"closed"}),
    "closed":      frozenset(),   # 终态
}

# 流转时允许顺带落地的产出列白名单 (哪些列可由状态机流转写入)。是一张平表, 不按
# 目标态细分 —— 各具名流转函数 (start_ai/mark_patch_ready/... ) 自行决定在哪个态填
# 哪个字段; 此白名单只兜底挡住写入非产出列 (如 id/status/submitter 不该走这里改)。
_WRITABLE_FIELDS = {"branch_name", "diagnosis", "diff_ref", "test_result",
                    "good_commit", "resolved_ts"}


class ReportError(Exception):
    """User Report 状态机非法操作。Web 层 (MR-B) 翻成 4xx。"""


class IllegalTransition(ReportError):
    """企图从当前状态跳到一个不被允许的状态。"""


def can_transition(src: str, dst: str) -> bool:
    """src 状态能否合法流转到 dst。未知状态一律 False (fail closed)。"""
    return dst in _ALLOWED.get(src, frozenset())


def _require_transition(src: str, dst: str) -> None:
    if not can_transition(src, dst):
        raise IllegalTransition(
            f"非法状态流转: {src!r} -> {dst!r} "
            f"(允许: {sorted(_ALLOWED.get(src, ()))!r})")


# --- 创建 (仅登录用户可提, submitter 必填 —— 可追责, ADR-0020) --------------
def create(con, submitter: str, text: str | None = None, *,
           report_id: str | None = None, now: float | None = None) -> dict:
    """新建一条 User Report, 初始态 submitted。返回落地后的整行。

    submitter 必填 (仅登录用户可提交, 每条绑真实身份可追责); 空 submitter 拒绝。
    MR-A 只填 core 字段, 其余 (branch_name/diagnosis/...) 留 None 由后续票填。
    """
    if not submitter:
        raise ReportError("submitter 必填: 仅登录用户可提交反馈 (ADR-0020)")
    rid = report_id or f"ur-{uuid.uuid4().hex[:12]}"
    if store.get_user_report(con, rid) is not None:
        raise ReportError(f"User Report 已存在: {rid!r}")
    t = now if now is not None else time.time()
    store.upsert_user_report(con, {
        "id": rid,
        "submitter": submitter,
        "status": "submitted",
        "text": text,
        "created_ts": t,
        "updated_ts": t,
    })
    return store.get_user_report(con, rid)


def get(con, report_id: str) -> dict:
    r = store.get_user_report(con, report_id)
    if r is None:
        raise ReportError(f"User Report 不存在: {report_id!r}")
    return r


# --- 通用流转 (合法性守卫 + 带守卫原子写, 防 TOCTOU) -----------------------
def transition(con, report_id: str, dst: str, *,
               fields: dict | None = None, now: float | None = None) -> dict:
    """把一条 report 从当前态推进到 dst, 校验合法性并原子落地。

    - dst 不在当前态的允许集 -> IllegalTransition (不静默)。
    - 带 expected_from 守卫: 仅当此刻仍是读到的那个 src 才翻转; 命中 0 行 (被并发
      改动) -> IllegalTransition, 不覆盖别人的推进。
    - fields: 本次流转顺带落地的产出列 (仅白名单), 非法键 -> ValueError。
    """
    r = get(con, report_id)
    src = r["status"]
    _require_transition(src, dst)
    bad = set(fields or {}) - _WRITABLE_FIELDS
    if bad:
        raise ValueError(f"非法产出字段 {sorted(bad)!r} "
                         f"(允许: {sorted(_WRITABLE_FIELDS)!r})")
    if not store.set_user_report_status(con, report_id, dst,
                                        expected_from=src, fields=fields,
                                        now=now):
        cur = store.get_user_report(con, report_id)
        raise IllegalTransition(
            f"流转失败: {report_id!r} 已不在 {src!r} "
            f"(当前 {cur['status'] if cur else '不存在'!r}, 可能被并发改动)")
    return store.get_user_report(con, report_id)


# --- 具名流转 (语义化包装, 让 MR-B/C/D 调用点自解释) -----------------------
def enqueue(con, report_id: str, **kw) -> dict:
    """submitted -> queued: 入 cron 队列 (也用于 needs-human/ai-failed 重试再入队)。"""
    return transition(con, report_id, "queued", **kw)


def start_ai(con, report_id: str, *, branch_name: str | None = None,
             **kw) -> dict:
    """queued -> ai-working: 修复 Agent 领走, 顺带记隔离 worktree 分支名 (C)。"""
    fields = dict(kw.pop("fields", {}) or {})
    if branch_name is not None:
        fields["branch_name"] = branch_name
    return transition(con, report_id, "ai-working", fields=fields or None, **kw)


def mark_patch_ready(con, report_id: str, *, diff_ref: str | None = None,
                     test_result: str | None = None, **kw) -> dict:
    """ai-working -> patch-ready: 低危 diff + 冒烟过, 附 diff/测试结果 (C), 等 owner 审。"""
    fields = dict(kw.pop("fields", {}) or {})
    if diff_ref is not None:
        fields["diff_ref"] = diff_ref
    if test_result is not None:
        fields["test_result"] = test_result
    return transition(con, report_id, "patch-ready", fields=fields or None, **kw)


def mark_needs_human(con, report_id: str, *, diagnosis: str | None = None,
                     **kw) -> dict:
    """-> needs-human: 碰禁区/改不了/owner 拒绝/金丝雀回滚, 转人工附诊断。

    合法来源: ai-working (Agent 判定) / patch-ready (owner 拒绝或金丝雀失败)。
    """
    fields = dict(kw.pop("fields", {}) or {})
    if diagnosis is not None:
        fields["diagnosis"] = diagnosis
    return transition(con, report_id, "needs-human", fields=fields or None, **kw)


def mark_ai_failed(con, report_id: str, *, diagnosis: str | None = None,
                   **kw) -> dict:
    """ai-working -> ai-failed: 试了但测试没过。"""
    fields = dict(kw.pop("fields", {}) or {})
    if diagnosis is not None:
        fields["diagnosis"] = diagnosis
    return transition(con, report_id, "ai-failed", fields=fields or None, **kw)


def resolve(con, report_id: str, *, good_commit: str | None = None,
            now: float | None = None, **kw) -> dict:
    """patch-ready -> resolved: owner 批准且金丝雀过, 修复上线 (D)。

    顺带记 good_commit (回滚锚点) 与 resolved_ts (上线时间)。
    """
    t = now if now is not None else time.time()
    fields = dict(kw.pop("fields", {}) or {})
    fields["resolved_ts"] = fields.get("resolved_ts", t)
    if good_commit is not None:
        fields["good_commit"] = good_commit
    return transition(con, report_id, "resolved", fields=fields, now=t, **kw)


def close(con, report_id: str, **kw) -> dict:
    """-> closed: 终态收口, 通知提交者。合法来源: resolved / needs-human / ai-failed。"""
    return transition(con, report_id, "closed", **kw)


# === MR-B (#56): 读出视图裁剪 (RBAC 在存储行之上按角色裁字段) =================
# 立身之本 (PRD story 5 / ADR-0020): 提交者只见状态, 看不到 diff / 诊断 / 分支 /
# 测试结果 —— 免内部代码细节外泄。owner 反馈台看全量。裁剪在读出后做 (存储层照存
# 全字段, 谁能看由这一层决定), 与 logview raw 仅 owner/AI 可见同构。

# 提交者可见的字段白名单: 只有「我这条反馈现在到哪一步了」需要的。
_SUBMITTER_FIELDS = ("id", "submitter", "status", "text",
                     "created_ts", "updated_ts")

# 状态 -> 给提交者看的人话进展 (PRD story 3: 处理中/已修复/需人工, 不暴露内部态名)。
_SUBMITTER_STATUS_LABEL = {
    "submitted":   "已收到",
    "queued":      "处理中",
    "ai-working":  "处理中",
    "patch-ready": "处理中",
    "needs-human": "需人工处理",
    "ai-failed":   "需人工处理",
    "resolved":    "已修复",
    "closed":      "已关闭",
}


def submitter_view(row: dict) -> dict:
    """把一条 report 裁成提交者可见视图: 仅状态类字段 + 人话进展, 无 diff/诊断。

    ADR-0020 story 5: 提交者不应看到补丁 diff 或内部诊断。此函数是那条边界的
    唯一出口 —— 只放行 _SUBMITTER_FIELDS, 内部字段 (branch_name/diagnosis/diff_ref/
    test_result/good_commit) 一律不带出。
    """
    out = {k: row.get(k) for k in _SUBMITTER_FIELDS}
    out["status_label"] = _SUBMITTER_STATUS_LABEL.get(row.get("status"), "处理中")
    return out


def console_view(row: dict) -> dict:
    """反馈台(owner)视图: 原样带全字段。

    MR-B 只做只读骨架 —— diff 面板 / 批准按钮由 MR-C、MR-D 各自加, 此处不预造。
    高亮标记(needs-human / ai-failed 优先处理, story 20)由前端据 status 派生。
    """
    return dict(row)


def list_for_submitter(con, submitter: str) -> list[dict]:
    """提交者查自己的全部反馈(裁成 submitter_view, 无 diff/诊断)。"""
    return [submitter_view(r) for r in store.reports_for_submitter(con, submitter)]


def list_for_console(con) -> list[dict]:
    """反馈台全量(owner 专属, console_view)。两条流不混 —— 只碰 user_report。"""
    return [console_view(r) for r in store.all_user_reports(con)]
