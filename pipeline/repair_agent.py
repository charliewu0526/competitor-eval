"""MR-C (#57): 修复 Agent 逻辑 + 低危白名单/硬禁区 (PRD #54 / ADR-0020~0023).

把一条 `queued` 的 User Report 变成一份候选补丁的**纯逻辑层**, 全部可离线单测,
不真调 AI。本票只做「给定一个(可 fake 的)agent, 如何安全地驱动它并消化它的产物」;
真正把 violoop generative 任务接到 cron 运行时上是 C2 的事。

职责 (逐条对应 #57):
  1. 准备隔离 git worktree, 不污染主工作树 (GitWorktree, 测试用 fake 替身)。
  2. 拼多模态 prompt(反馈文字 + 截图 + 后端日志 + 相关源码)—— build_prompt。
  3. 判定改动是否落在低危白名单 / 是否触碰硬禁区 (ADR-0022) —— classify_scope。
     这是全模块的立身之本, 也是最强的 prompt-injection 护栏: 注入指令再花哨, 也越不
     出「只能改低危文件」这道物理边界 (碰禁区 -> 不自动改, 转人工附原因)。
  4. 把 agent 结果回写 MR-A 状态机 -> patch-ready / needs-human / ai-failed —— run_repair。
  5. owner 专属可见 diff/测试/诊断; 提交者侧仍不可见 —— strip_repair_fields。

Agent 契约 (仿 review_fakes / intake_fakes: 生产实现与 fake 同契约, 驱动层分不出真假):
    agent(prompt: dict) -> dict {
        "changed_files": [相对仓库根的路径, ...],   # agent 声称改了哪些文件
        "diff":          "<unified diff 文本>",       # 候选补丁
        "diagnosis":     "一句话诊断",
        "no_fix":        bool,   # True = agent 无从下手/放弃 -> 直接转人工
    }
真 agent (violoop heavy 档) 在 C2 接入; 本票测试一律用 repair_fakes 注入假 agent。
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import time
import uuid

from pipeline import reports

ROOT = pathlib.Path(__file__).resolve().parent.parent


# =========================================================================
# 作用域判定 (ADR-0022): 低危白名单 + 硬禁区
# =========================================================================
# 立身之本 = prompt-injection 物理边界。判定只看「改动落在哪些文件」, 与文件内容
# /agent 说了什么无关 —— 注入指令再花哨, 越不出文件路径这道物理边界。
#
# 判定原则 (fail closed):
#   - 任一改动文件命中硬禁区   -> forbidden (转人工, 绝不自动改)
#   - 全部改动文件命中低危白名单 -> low-risk (可自动起草补丁)
#   - 出现既不在白名单也不在禁区的文件 (灰区) -> forbidden
#     (未知即拒: 只有明确低危才放行, 不给「默认允许」的缝隙)
#   - 空改动列表 -> forbidden (没有可自动落地的改动)

# 硬禁区: 错了会伤数据 / 破安全 / 毁部署的地方。优先级最高 —— 命中即 forbidden,
# 即便同批还改了低危文件 (一颗老鼠屎)。用「路径片段」匹配, 覆盖后端敏感模块 +
# 任意目录下的 secrets/部署脚本。
_FORBIDDEN_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p) for p in (
    # 鉴权 / RBAC (登录与角色)
    r"(^|/)pipeline/auth\.py$",
    r"(^|/)pipeline/rbac\.py$",
    r"(^|/)pipeline/authorize\.py$",
    r"(^|/)frontend/src/auth\.jsx$",
    # DB schema / 迁移 / 存储落地层
    r"(^|/)pipeline/store\.py$",
    r"(^|/)pipeline/db\.py$",
    r"(?i)(^|/)migrat",           # 任意 migration 脚本/目录
    r"(?i)(^|/)schema\b",
    # 脱敏规则
    r"(^|/)pipeline/logview\.py$",
    r"(?i)desensit",
    r"(?i)redact",
    # 删数据的代码 / 存储原语本身 (artifact_store 落盘删档)
    r"(^|/)pipeline/artifact_store\.py$",
    # .env / secrets / 密钥
    r"(?i)(^|/)\.env",
    r"(?i)secret",
    r"(?i)\.pem$",
    r"(?i)credential",
    # 部署脚本 / 运维
    r"(?i)(^|/)deploy",
    r"(^|/)scripts/serve",
    r"(?i)\.(sh|service|plist)$",
    r"(?i)(^|/)(dockerfile|docker-compose)",
    r"(?i)(^|/)\.github/",
))

# 低危白名单: 前端展示层 —— 错了也只是界面坏, 不伤数据/安全/部署。
# 只有全部改动都命中这里才放行自动补丁。
# 放宽 (2026-07-30): 原白名单只列 pages/components/css/glossary, 把 App.jsx(根布局/
# 路由/菜单)、main.jsx、api.js 等 frontend/src 下的展示层文件都当灰区"未知即拒",
# 导致大量本可自动修的前端 bug(如"边栏跟随下滑"要改 App.jsx)被挡下转人工。
# 现放宽为: frontend/src 下的 .jsx/.js/.ts/.tsx/样式 一律低危 —— 前端整体是展示层,
# 改坏顶多界面坏, 有前端构建闸兜底。**唯一例外 auth.jsx 已在硬禁区**(禁区优先级
# 高于白名单, is_low_risk 里先查禁区), 故放宽不会松动鉴权边界。后端 .py 仍是灰区
# (未知即拒), 硬禁区(鉴权/schema/脱敏/删数据/secrets/部署)一字未动。
_LOWRISK_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p) for p in (
    r"(^|/)frontend/src/.*\.(jsx?|tsx?)$",     # 前端展示层脚本(页面/组件/App/路由/api 等)
    r"(?i)\.(css|scss|less)$",                 # 样式
    r"(^|/)frontend/(index\.html|.*\.(json))$",  # 前端入口 html / 配置 json(展示层)
))


def _match_any(path: str, patterns) -> bool:
    return any(p.search(path) for p in patterns)


def is_forbidden(path: str) -> bool:
    """单文件是否落在硬禁区 (ADR-0022)。禁区优先级高于白名单。"""
    return _match_any(str(path), _FORBIDDEN_PATTERNS)


def is_low_risk(path: str) -> bool:
    """单文件是否落在低危白名单。禁区命中的文件即便也像低危, 也不算低危。"""
    p = str(path)
    if is_forbidden(p):
        return False
    return _match_any(p, _LOWRISK_PATTERNS)


def classify_scope(changed_files) -> dict:
    """判定一组改动文件的作用域, 返回决策 dict。

    返回 {"verdict": "low-risk"|"forbidden",
          "forbidden": [...], "low_risk": [...], "gray": [...],
          "reason": str}
    fail closed: 空列表 / 任一禁区命中 / 任一灰区文件 -> forbidden。
    """
    files = [str(f) for f in (changed_files or [])]
    forbidden = [f for f in files if is_forbidden(f)]
    low = [f for f in files if is_low_risk(f)]
    gray = [f for f in files if f not in forbidden and f not in low]

    if not files:
        return {"verdict": "forbidden", "forbidden": [], "low_risk": [],
                "gray": [], "reason": "空改动: 没有可自动落地的改动, 转人工"}
    if forbidden:
        return {"verdict": "forbidden", "forbidden": forbidden,
                "low_risk": low, "gray": gray,
                "reason": f"触碰硬禁区 {forbidden!r} (鉴权/schema/脱敏/删数据/"
                          f"secrets/部署), 绝不自动改, 转人工 (ADR-0022)"}
    if gray:
        return {"verdict": "forbidden", "forbidden": [], "low_risk": low,
                "gray": gray,
                "reason": f"灰区文件 {gray!r} 不在低危白名单 (未知即拒, "
                          f"只自动改前端展示层), 转人工"}
    return {"verdict": "low-risk", "forbidden": [], "low_risk": low,
            "gray": [], "reason": f"全部改动落在低危白名单 {low!r}, 可自动起草补丁"}


# =========================================================================
# 隔离 git worktree (ADR-0021): Agent 在分支上干活, 不污染主工作树/正在跑的评测
# =========================================================================
class GitWorktree:
    """一次性隔离 worktree 的上下文管理器。

    真实实现: `git worktree add -b <branch> <dir> <base>` 建独立工作树, 退出时
    `git worktree remove --force` 清掉。Agent 只在这里读写, 主工作树纹丝不动。

    测试用 FakeWorktree 替身 (repair_fakes) 隔离 —— 单测不真 fork 进程/建工作树。
    契约: __enter__ 返回一个有 .path (工作目录) 与 .branch (分支名) 的对象。
    """

    def __init__(self, *, base: str = "HEAD", branch: str | None = None,
                 root: str | pathlib.Path | None = None,
                 worktrees_dir: str | pathlib.Path | None = None):
        self.repo_root = pathlib.Path(root) if root else ROOT
        self.branch = branch or f"repair/ur-{uuid.uuid4().hex[:8]}"
        self.base = base
        base_dir = (pathlib.Path(worktrees_dir) if worktrees_dir
                    else self.repo_root / "board" / "repair-worktrees")
        self.path = base_dir / self.branch.replace("/", "_")
        self._added = False

    def _git(self, *args: str) -> str:
        out = subprocess.run(["git", *args], cwd=str(self.repo_root),
                             capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} 失败: {out.stderr.strip()}")
        return out.stdout

    def __enter__(self) -> "GitWorktree":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "-b", self.branch, str(self.path), self.base)
        self._added = True
        return self

    def __exit__(self, *exc) -> None:
        if self._added:
            try:
                self._git("worktree", "remove", "--force", str(self.path))
            finally:
                # 分支删掉, 不留一堆 repair/ur-* 悬着 (best-effort)。
                subprocess.run(["git", "branch", "-D", self.branch],
                               cwd=str(self.repo_root), capture_output=True)


# =========================================================================
# 多模态 prompt 拼装: 反馈文字 + 截图 + 后端日志 + 相关源码
# =========================================================================
def build_prompt(report: dict, *, screenshots=None, log_excerpt: str | None = None,
                 source_files=None) -> dict:
    """把定位一个前端 bug 所需的多模态上下文拼成一个 prompt dict。

    结构化 dict (不是拼字符串): 真 agent 接入 (C2) 时按此喂 violoop generative 任务
    的 text + image blocks。本层只负责组装, 不调 AI。

    - report: MR-A 的 user_report 行 (取 text/id/submitter)。
    - screenshots: 截图路径列表 (走 artifact_store, 多模态 image blocks 载体)。
    - log_excerpt: 后端日志 raw 视图 (logview, 仅 owner/AI 可见)。
    - source_files: [(相对路径, 内容), ...] 相关源码切片。
    prompt 里明确圈死作用域 (低危白名单), 让注入指令即便被读进来也越不出边界。
    """
    return {
        "report_id": report.get("id"),
        "text": report.get("text") or "",
        "screenshots": list(screenshots or []),
        "log_excerpt": log_excerpt or "",
        "source_files": list(source_files or []),
        # 硬约束一并喂给 agent (第一道软护栏; 物理护栏是 classify_scope 兜底)。
        "scope_instruction": (
            "只允许修改前端组件/页面/样式/文案/纯展示逻辑 (低危白名单)。"
            "严禁修改鉴权/RBAC、DB schema/迁移、脱敏规则、删数据代码、"
            ".env/secrets、部署脚本 —— 若 bug 需要碰这些, 不要改, 直接说明原因。"
        ),
    }


# =========================================================================
# 驱动 Agent + 消化产物 -> 回写 MR-A 状态机
# =========================================================================
def _run_tests(cwd: str, test_cmd=None) -> tuple[bool, str]:
    """在 worktree 里跑测试, 返回 (passed, 摘要文本)。

    默认跑 pytest -q。测试用 fake worktree 时由调用方注入 test_runner 替身,
    不真起子进程。
    """
    cmd = test_cmd or ["python", "-m", "pytest", "-q"]
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                         timeout=600)
    tail = (out.stdout or out.stderr).strip().splitlines()[-3:]
    return out.returncode == 0, "\n".join(tail)


def run_repair(con, report_id: str, agent, *,
               worktree_factory=None, test_runner=None,
               prompt_ctx: dict | None = None, now: float | None = None) -> dict:
    """驱动一条 report 走完一轮 AI 修复, 把结果安全落到状态机。

    流程 (queued -> ai-working -> 三分叉之一):
      1. 领走 report: queued -> ai-working, 记 branch_name。
      2. 建隔离 worktree (worktree_factory, 测试注入 fake)。
      3. build_prompt -> 调 agent(prompt)。
      4. agent 放弃 (no_fix) -> needs-human, 附诊断。
      5. classify_scope(changed_files):
           forbidden -> needs-human (绝不自动改, 附禁区原因)。
           low-risk  -> 跑测试:
               过 -> patch-ready (附 diff_ref + test_result)。
               挂 -> ai-failed (附测试摘要)。
    返回落地后的 report 行。真 agent 不进单测 —— 测试用 repair_fakes 注入。
    """
    t = now if now is not None else time.time()
    r = reports.get(con, report_id)
    if r["status"] != "queued":
        raise reports.ReportError(
            f"run_repair 只处理 queued 的 report, 当前 {r['status']!r}")

    factory = worktree_factory or (lambda: GitWorktree())
    wt = factory()
    with wt as work:
        branch = getattr(work, "branch", None)
        reports.start_ai(con, report_id, branch_name=branch, now=t)

        prompt = build_prompt(r, **(prompt_ctx or {}))
        result = agent(prompt) or {}

        if result.get("no_fix"):
            diag = result.get("diagnosis") or "AI 无从下手, 转人工"
            return reports.mark_needs_human(con, report_id, diagnosis=diag)

        scope = classify_scope(result.get("changed_files"))
        if scope["verdict"] == "forbidden":
            diag = result.get("diagnosis") or ""
            reason = scope["reason"] if not diag else f"{diag} | {scope['reason']}"
            return reports.mark_needs_human(con, report_id, diagnosis=reason)

        # 低危区: 把 diff 落到 artifact 引用 (真实现存盘; 测试注入路径), 跑测试。
        diff_ref = _persist_diff(work, report_id, result.get("diff") or "")
        runner = test_runner or (lambda: _run_tests(str(getattr(work, "path", "."))))
        passed, summary = runner()
        if passed:
            return reports.mark_patch_ready(
                con, report_id, diff_ref=diff_ref,
                test_result=f"passed: {summary}")
        return reports.mark_ai_failed(
            con, report_id,
            diagnosis=f"低危补丁已产出但测试未过: {summary}")


def _persist_diff(work, report_id: str, diff: str) -> str:
    """把候选补丁 diff 落到一个稳定路径引用 (库里只存引用, 遵 ADR-0019)。

    真实现写到 board/repair-diffs/<report_id>.diff; work 有 .path 时优先写进
    worktree 便于人工审阅。返回绝对路径字符串。
    """
    base = ROOT / "board" / "repair-diffs"
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{report_id}.diff"
    p.write_text(diff, encoding="utf-8")
    return str(p.resolve())


# =========================================================================
# owner 专属可见性: 提交者看不到 diff/诊断/内部字段 (PRD story 5)
# =========================================================================
# 只有 owner (以及 AI 自身) 能看到的内部修复字段。提交者列表视图必须剥掉,
# 以免内部代码细节 (diff 路径/诊断/分支) 外泄。
_OWNER_ONLY_FIELDS = ("diff_ref", "diagnosis", "test_result",
                      "branch_name", "good_commit")


def strip_repair_fields(report: dict) -> dict:
    """返回一份剥掉 owner-only 内部字段的 report 副本, 给提交者/非 owner 看。

    保留 id/status/text/时间戳等提交者有权知道的进展信息; 抹掉 diff/诊断等内部细节
    (PRD story 5: 提交者不应看到 diff 或内部诊断)。
    """
    return {k: v for k, v in report.items() if k not in _OWNER_ONLY_FIELDS}


def view_for(report: dict, *, role: str | None) -> dict:
    """按角色投影一条 report: owner 见全字段, 其余人见剥离版。"""
    if role == "owner":
        return dict(report)
    return strip_repair_fields(report)

