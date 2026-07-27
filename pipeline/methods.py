"""MR-14 (#50): 方法初稿提炼 + 复核闸 + 导出 (方法复核闸).

沉淀方法给研发。intern 在差距证据包(分数差 + Finding + 机理, 见 gap_report)上
提炼「方法」初稿(Method, status=draft); 初稿必须经 reviewer/PM 把关(approved)
才能导出(exported)给研发。防新人没看懂机理的瞎提炼污染系统可信度。

状态机(方法复核闸, 单向不可逆):
    draft --approve(reviewer/PM)--> approved --export(reviewer/PM)--> exported

本切片只补 store + RBAC 之上那层「策略 + 导出渲染」:
  * store 已有 methods 表 + upsert/set_method_status/all_methods/get_method(MR-1 地基)。
  * RBAC 已有 gate_method=reviewer(MR-4); draft 创建复用 intern 级 submit
    (story 34: intern 能创建初稿)。这里不新增权限键(RBAC PERMISSIONS 已被
    test_rbac_mr4 全矩阵锁定)。

复核闸铁律(#50 AC):
  1. intern 能在差距证据包上创建 draft。
  2. draft 未经把关不能导出 —— export 前必须已 approved, 否则 NotApproved 拒绝。
  3. reviewer/PM 把关 draft->approved(gate_method, intern 被拒)。
  4. approved 的 Method 才能导出为研发可读格式(竞品为何强 + Violoop 落地建议)。

立身之本: 导出只转述人写的初稿 + 机器已产出的差距证据(分数差/机理), 绝不代替
人下判断、不从竞品自述编造机理; 机理未分析/闭源如实标 unavailable。
"""
from __future__ import annotations

from pipeline import store
from pipeline import rbac as RBAC

# 状态机常量: 单向 draft -> approved -> exported。
DRAFT = "draft"
APPROVED = "approved"
EXPORTED = "exported"
STATUS_VALUES = (DRAFT, APPROVED, EXPORTED)


class MethodError(Exception):
    """方法复核闸策略层错误。Web 层翻成 4xx。"""


class MethodNotFound(MethodError):
    """方法初稿不存在。Web -> 404。"""


class NotApproved(MethodError):
    """draft 未经把关就想导出 —— 复核闸拦截 (#50 AC2)。Web -> 409。"""


class IllegalMethodState(MethodError):
    """状态流转非法(如已 exported 再改 / 重复审批)。Web -> 409。"""


# --- 1. intern 创建方法初稿 (draft) ---------------------------------------
def draft_method(con, *, author: dict | None, task_id: str, product: str,
                 draft: str) -> dict:
    """intern 在差距证据包上创建方法初稿(#50 AC1, story 34)。

    - author 需 'submit' 权限(intern 起)—— 任意已登录执行者可提炼, 未登录被拒。
    - draft 必须非空 —— 空初稿没有沉淀价值, 拒绝。
    - 落库即 status=draft; 把关前不可导出(下面 export_method 守卫)。
    返回落库后的 method 行。
    """
    RBAC.require(author, "submit")
    if not (draft and str(draft).strip()):
        raise MethodError("方法初稿正文不能为空(要在差距证据包上提炼可迁移做法)")
    mid = store.upsert_method(con, {
        "task_id": task_id, "product": product,
        "draft": str(draft).strip(), "status": DRAFT,
    })
    return store.get_method(con, mid)


# --- 2. reviewer/PM 把关 draft -> approved --------------------------------
def approve_method(con, *, reviewer: dict | None, method_id: int) -> dict:
    """reviewer/PM 把关方法初稿 draft->approved(#50 AC3, story 35)。

    - reviewer 需 'gate_method' 权限(reviewer 起, intern 被拒 —— 新人不能自批
      自己的提炼, 呼应职责边界)。
    - 该 Method 必须处于 draft —— 已 approved/exported 再批是非法流转。
    gated_by 绑定把关者身份(审计: 谁放行的)。返回更新后的 method 行。
    """
    RBAC.require(reviewer, "gate_method")
    m = store.get_method(con, method_id)
    if m is None:
        raise MethodNotFound(f"方法初稿不存在: {method_id!r}")
    if m["status"] != DRAFT:
        raise IllegalMethodState(
            f"方法 {method_id!r} 当前 {m['status']!r}, 只有 draft 可被把关为 approved")
    store.set_method_status(con, method_id, APPROVED,
                            gated_by=(reviewer or {}).get("id"))
    return store.get_method(con, method_id)


# --- 3. 导出 approved -> exported (研发可读格式) --------------------------
def export_method(con, *, actor: dict | None, method_id: int,
                  registry=None) -> dict:
    """把已把关的 Method 导出为研发可读格式(#50 AC4, story 36)。

    复核闸核心守卫(#50 AC2): 未经把关(status != approved)一律 NotApproved 拒绝
    —— draft 不能越过 reviewer 直接进研发。已 exported 幂等返回(不重复渲染改状态)。

    - actor 需 'gate_method' 权限(导出属把关链后段, reviewer/PM; intern 被拒)。
    - 渲染出「竞品为何强 + Violoop 落地建议」的 markdown(见 render_method),
      并把状态推进 exported。
    返回 {method, document}。
    """
    RBAC.require(actor, "gate_method")
    m = store.get_method(con, method_id)
    if m is None:
        raise MethodNotFound(f"方法初稿不存在: {method_id!r}")
    if m["status"] == DRAFT:
        raise NotApproved(
            f"方法 {method_id!r} 仍是 draft, 未经 reviewer/PM 把关不能导出给研发 "
            f"(方法复核闸: 防没看懂机理的瞎提炼污染可信度)")
    if m["status"] == APPROVED:
        store.set_method_status(con, method_id, EXPORTED)
        m = store.get_method(con, method_id)
    # status == EXPORTED (刚推进或本就已导出): 幂等渲染, 供研发反复取用。
    doc = render_method(con, m, registry=registry)
    return {"method": m, "document": doc}


def preview_export(con, method_id: int, *, registry=None) -> str:
    """只渲染不改状态(给 reviewer 把关前预览「导出后研发看到什么」)。

    不做权限/状态守卫 —— 纯派生渲染, 调用方(Web reviewer 端)已鉴权。
    """
    m = store.get_method(con, method_id)
    if m is None:
        raise MethodNotFound(f"方法初稿不存在: {method_id!r}")
    return render_method(con, m, registry=registry)


# --- 渲染: 研发可读格式 (竞品为何强 + Violoop 落地建议) --------------------
def render_method(con, method: dict, *, registry=None) -> str:
    """把一条 Method 渲染成研发可读 markdown。

    结构 = 差距证据(机器已产出的分数差 + 机理, 从 gap_report 派生)+ 人写的方法
    初稿(竞品为何强 + Violoop 落地建议)。研发照此改进产品, 不必读一堆原始截图。

    立身之本: 证据块只转述机器/人已有产出 —— 分数差是算术, 机理来自 code-analysis
    (闭源/未分析如实标 unavailable), 初稿是人写的判断。绝不在此编造机理或代下结论。
    """
    task_id = method["task_id"]
    product = method["product"]
    # 差距证据(可选): 从 gap_report 派生该题该竞品 vs 基线的分数差 + 机理。
    diff_line, mech_line = _evidence_for(con, task_id, product, registry=registry)

    lines = [
        f"# 方法沉淀: {product} @ {task_id}",
        "",
        f"- 竞品: **{product}**",
        f"- 来源任务: `{task_id}`",
        f"- 把关状态: {method['status']}"
        + (f" (把关人: {method['gated_by']})" if method.get("gated_by") else ""),
        "",
        "## 差距证据(机器派生, 只标事实)",
        f"- 分数差(vs Violoop 基线): {diff_line}",
        f"- 开源机理: {mech_line}",
        "",
        "## 竞品为何强 + Violoop 落地建议(人工提炼)",
        method["draft"],
        "",
        "---",
        "> 本文档由方法复核闸导出: 初稿经 reviewer/PM 把关(approved)后方可导出。"
        " 差距证据为机器派生事实, 落地建议为人工判断。",
    ]
    return "\n".join(lines)


def _evidence_for(con, task_id: str, product: str, *, registry=None):
    """从 gap_report 挖该 (task, product) 的分数差 + 机理, 供导出文档转述。

    读不到(该题没跑分 / 没这个竞品)-> 如实标「unavailable」, 绝不编造。
    返回 (分数差描述, 机理描述) 两个人话串。
    """
    diff_line = "unavailable(该题暂无可比分数)"
    mech_line = "unavailable(闭源或尚未做源码机理分析)"
    try:
        from pipeline import gap_report as GR
        rep = GR.from_store(con, task_id, registry=registry)
    except Exception:
        return diff_line, mech_line
    for d in rep.score_diffs:
        if d.product == product:
            if d.cannot_reach:
                diff_line = "cannot-reach(该竞品够不着此题, 未参赛)"
            elif d.diff is None:
                diff_line = "unavailable(缺基线或本产品分数, 不可比)"
            else:
                sign = "领先" if d.diff > 0 else ("落后" if d.diff < 0 else "持平")
                diff_line = (f"{d.diff:+.3f}({sign} Violoop; "
                             f"本产品 {d.sample_score}, 基线 {d.baseline_score})")
            break
    for mrow in rep.mechanisms:
        if mrow.product == product:
            if mrow.mechanism:
                repo = f" [repo: {mrow.repo}]" if mrow.repo else ""
                mech_line = f"{mrow.mechanism}{repo}"
            elif not mrow.is_open_source:
                mech_line = "unavailable(闭源竞品, 拿不到源码)"
            else:
                mech_line = "unavailable(开源但尚未做机理分析)"
            break
    return diff_line, mech_line


def list_methods(con, status: str | None = None) -> list[dict]:
    """列出方法初稿(可按 status 过滤)。派生只读, 供前端方法看板/复核队列。"""
    return store.all_methods(con, status=status)
