"""MR-C2 (#58): 修复 Agent 的 cron 运行时装配 CLI (PRD #54 / ADR-0021~0022).

把 MR-C 的纯逻辑护栏 (repair_agent) 接到真实运行时: 一个 `*/5` 的 violoop
generative agenda 任务, AI 循环本身充当修复 Agent。本 CLI 是 AI 与状态机之间的
**确定性夹层** —— AI 只负责「读上下文 + 在隔离 worktree 里改低危前端文件」这段创造性
中段, 领取/判定/回写全在这里, 物理护栏不受 prompt 注入摆布。

两个子命令 (AI 在一次 agenda run 内先 claim 再 finalize):

  claim   原子领走最老的一条 queued User Report:
            queued -> ai-working (状态机守卫 + expected_from, 天然串行, 不打架),
            建隔离 git worktree (非主工作树),
            把多模态上下文 (反馈文字 + 截图路径 + 后端日志 + 相关源码) dump 到
            <worktree>/.repair_context.json,
            以 JSON 打印 {report_id, worktree, branch, context_file} 给 AI。
          没有 queued -> 打印 {report_id: null} 并 0 退出 (cron 空转, 不报错)。

  finalize 收口一条已 claim 的 report (AI 改完 worktree 后调):
            对 worktree 算**真实 git diff** (git diff --name-only), 用 classify_scope
            判定 AI **实际改了哪些文件** —— 信 git 不信 AI 自报的 changed_files,
            这是最强抗注入护栏 (注入指令再花哨也越不出「实际落盘的文件路径」)。
              空改动 / no_fix     -> needs-human (附诊断)
              触碰硬禁区 / 灰区    -> needs-human (绝不自动上, 附禁区原因), 丢弃改动
              全低危 -> 跑测试:
                过 -> patch-ready (落真实 diff 到 diff_ref + test_result)
                挂 -> ai-failed (附测试摘要)
            无论走哪条分支, 最后都 remove worktree + 删分支 (不留悬垂)。

并发: cron 每 5 分钟串行触发 + claim 的状态机 expected_from 守卫, 双重保证不会有
两个 agent 同时改同一仓库 (系统此前踩过并发踩踏, 见 ADR-0021)。

运行时前提 (写入 CONTEXT / 运行说明):
  * 依赖 owner 机器上的 violoop 在线才产补丁; violoop 挂了队列保证反馈不丢 (排队等)。
  * 连**后端同一个库**: 读 board/pg_uri.txt (自托管 Postgres), 无则回落默认 SQLite。
  * worktree 落 board/repair-worktrees/, diff 落 board/repair-diffs/。

真 agent (violoop heavy 档) 不进单测。本 CLI 的 claim/finalize 用真 git 临时仓 +
注入 test_runner 离线单测 (test_repair_runner_mrc2), 不真调 AI。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import artifact_store as ART
from pipeline import reports
from pipeline import repair_agent as RA
from pipeline import store

_CONTEXT_NAME = ".repair_context.json"


# =========================================================================
# 连后端同一个库: 读 board/pg_uri.txt (自托管 Postgres), 无则回落默认 SQLite
# =========================================================================
def resolve_db_url(explicit: str | None = None) -> str | None:
    """决定连哪个库。优先级: 显式参数 > board/pg_uri.txt > DATABASE_URL 环境 > None(SQLite)。

    cron 任务与后端 uvicorn 是两个进程, 但必须读写**同一个库**才能扫到用户刚提交的
    queued 反馈。后端 run_pg_backend.py 会把自托管 Postgres 的 uri 写进 board/pg_uri.txt,
    这里读它对齐。文件不存在(纯 SQLite 部署)-> None, store.connect 走默认 SQLite。
    """
    if explicit:
        return explicit
    uri_file = ROOT / "board" / "pg_uri.txt"
    if uri_file.is_file():
        txt = uri_file.read_text(encoding="utf-8").strip()
        if txt:
            return txt
    import os
    return os.environ.get("DATABASE_URL")


def _connect(db_url: str | None):
    """连库, 按方言路由: postgres URL 走 url=, 其余(sqlite 文件路径/None)走 db_path=。

    生产: resolve_db_url 从 board/pg_uri.txt 得到 postgres URL -> url=。
    测试/纯 SQLite 部署: 得到一个文件路径或 None -> db_path=(None 落默认库)。
    不 skip_migrate: CREATE TABLE IF NOT EXISTS 幂等, 保证 cron 首次也能建表
    (每 5 分钟一次, 代价可忽略)。
    """
    from pipeline import db as _db
    resolved = resolve_db_url(db_url)
    if resolved and _db.dialect_for(resolved) == "postgres":
        return store.connect(url=resolved)
    return store.connect(db_path=resolved)


# =========================================================================
# 收集一条 report 的多模态修复上下文 (截图 + 后端日志 + 相关源码切片)
# =========================================================================
def _read_log_excerpt(report_id: str, *, max_chars: int = 8000) -> str:
    """读该 report 自动附带的后端日志快照 (MR-B 提交时落盘, 仅 owner/AI 可见)。"""
    logs = ART.list_report_uploads(report_id, "log")
    if not logs:
        return ""
    try:
        data = pathlib.Path(logs[0]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data[-max_chars:]


def _candidate_source_files(worktree: pathlib.Path, *, limit: int = 40) -> list[tuple[str, str]]:
    """给 AI 喂「可改区」的源码切片: 只列低危白名单目录下的前端文件 (页面/组件/样式)。

    故意只喂低危区 —— 既省 token, 又从上下文层面就把 AI 的注意力圈在可改边界内
    (物理护栏仍是 finalize 的 git diff 判定)。返回 [(相对路径, 内容), ...]。
    """
    out: list[tuple[str, str]] = []
    roots = [worktree / "frontend" / "src" / "pages",
             worktree / "frontend" / "src" / "components"]
    for base in roots:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if len(out) >= limit:
                break
            if p.is_file() and p.suffix in (".jsx", ".js", ".css", ".scss", ".less"):
                rel = str(p.relative_to(worktree))
                try:
                    out.append((rel, p.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    continue
    return out


# =========================================================================
# claim: 原子领走最老的 queued + 建隔离 worktree + dump 多模态上下文
# =========================================================================
def claim(db_url: str | None = None, *, worktree_factory=None) -> dict:
    """领走最老的一条 queued report, 建隔离 worktree, dump 上下文, 返回给 AI 的句柄。

    返回 {report_id, worktree, branch, context_file} 或 {report_id: None} (队列空)。
    状态机守卫 (queued -> ai-working, expected_from) 天然串行化并发领取。
    """
    con = _connect(db_url)
    queued = store.reports_by_status(con, "queued")
    if not queued:
        return {"report_id": None}
    r = queued[0]           # 最老优先 (reports_by_status 已 ORDER BY created_ts, id)
    rid = r["id"]

    # 建隔离 worktree。跨进程持有 -> 不用 with, 手动 __enter__; finalize 里 __exit__。
    wt = (worktree_factory() if worktree_factory else RA.GitWorktree(root=ROOT))
    work = wt.__enter__()
    branch = getattr(work, "branch", None)
    wt_path = pathlib.Path(getattr(work, "path", ROOT))

    # queued -> ai-working (记分支; 命中 0 行=被并发抢走 -> IllegalTransition, cron 下轮再来)
    try:
        reports.start_ai(con, rid, branch_name=branch)
    except reports.IllegalTransition:
        # 领取竞态: 别人已推进。清掉刚建的 worktree, 报空领取。
        wt.__exit__(None, None, None)
        return {"report_id": None}

    # 拼多模态上下文, dump 到 worktree 供 AI 读 (结构化 dict, 非拼字符串)。
    prompt = RA.build_prompt(
        r,
        screenshots=ART.list_report_uploads(rid, "screenshot"),
        log_excerpt=_read_log_excerpt(rid),
        source_files=_candidate_source_files(wt_path),
    )
    ctx_file = wt_path / _CONTEXT_NAME
    ctx_file.write_text(json.dumps(prompt, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    return {"report_id": rid, "worktree": str(wt_path),
            "branch": branch, "context_file": str(ctx_file)}


# =========================================================================
# finalize: 对 worktree 算真实 git diff -> 判定 -> 跑测试 -> 回写状态机 + 清理
# =========================================================================
def _git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _real_changed_files(worktree: pathlib.Path) -> list[str]:
    """worktree 里 AI 实际改了/加了哪些文件 —— 信 git 不信 AI 自报 (最强抗注入)。

    覆盖已跟踪改动 (diff --name-only) + 新增未跟踪文件 (ls-files --others)。
    忽略我们自己 dump 的 .repair_context.json。
    """
    changed: set[str] = set()
    out = _git(worktree, "diff", "--name-only")
    if out.returncode == 0:
        changed.update(f for f in out.stdout.splitlines() if f.strip())
    out = _git(worktree, "ls-files", "--others", "--exclude-standard")
    if out.returncode == 0:
        changed.update(f for f in out.stdout.splitlines() if f.strip())
    changed.discard(_CONTEXT_NAME)
    return sorted(changed)


def _worktree_diff(worktree: pathlib.Path) -> str:
    """worktree 相对 HEAD 的完整补丁 (含新增文件), 排除 .repair_context.json。"""
    _git(worktree, "add", "-A")
    _git(worktree, "reset", "--", _CONTEXT_NAME)   # 别把上下文文件卷进补丁
    out = _git(worktree, "diff", "--cached")
    return out.stdout


def _main_repo_root(wt_path: pathlib.Path) -> pathlib.Path:
    """从一个 worktree 反推它所属的主仓根 (worktree remove 必须在主仓上跑)。

    `git rev-parse --git-common-dir` 给出共享的 .git 目录 (主仓的 <root>/.git),
    其父目录即主仓根。生产里就是 ROOT; 测试里是各自的临时仓 —— 不再硬编码 ROOT。
    """
    out = _git(wt_path, "rev-parse", "--git-common-dir")
    if out.returncode == 0 and out.stdout.strip():
        common = pathlib.Path(out.stdout.strip())
        if not common.is_absolute():
            common = (wt_path / common).resolve()
        return common.parent
    return ROOT


def _frontend_build(worktree: pathlib.Path) -> tuple[bool, str]:
    """对口验证闸: 在 worktree 里跑前端构建 (bun run build)。

    修复 Agent 按 ADR-0022 只改前端展示层文件, 所以它产出的补丁的正确验证闸是
    **前端能否构建通过**, 而不是全量后端 pytest —— 后者既跑不到点子上 (前端改动
    影响不了后端), 又因 git worktree 是干净检出、缺主树里那些未跟踪的 fixture
    (tasks/ 输入等) 而必然失败。呼应 MR-B 惯例「前端 vite build 通过」。

    node_modules 被 .gitignore, 干净 worktree 里没有 -> 从主仓 symlink 复用
    (免得每条反馈都 bun install 一遍)。
    """
    fe = worktree / "frontend"
    if not (fe / "package.json").is_file():
        return False, "worktree 缺 frontend/package.json, 无法构建"
    node_modules = fe / "node_modules"
    if not node_modules.exists():
        main_nm = ROOT / "frontend" / "node_modules"
        if main_nm.is_dir():
            try:
                node_modules.symlink_to(main_nm)
            except OSError as e:
                return False, f"链接 node_modules 失败: {e}"
    bun = _which_bun()
    out = subprocess.run([bun, "run", "build"], cwd=str(fe),
                         capture_output=True, text=True, timeout=600)
    tail = "\n".join((out.stdout + out.stderr).strip().splitlines()[-4:])
    return out.returncode == 0, tail


def _which_bun() -> str:
    """定位 bun (PATH 里没有时回落 violoop runtime 的 bun)。"""
    import shutil
    found = shutil.which("bun")
    if found:
        return found
    fallback = pathlib.Path.home() / (
        "Library/Application Support/violoop/runtime/bun/bin/bun")
    return str(fallback) if fallback.exists() else "bun"


def _cleanup_worktree(branch: str | None, wt_path: pathlib.Path) -> None:
    """移除 worktree + 删分支 (best-effort, 不留悬垂)。"""
    root = _main_repo_root(wt_path)
    _git(root, "worktree", "remove", "--force", str(wt_path))
    if branch:
        _git(root, "branch", "-D", branch)


def finalize(report_id: str, worktree: str, *, branch: str | None = None,
             db_url: str | None = None, test_runner=None,
             no_fix: bool = False, diagnosis: str = "") -> dict:
    """AI 改完 worktree 后收口: 真实 git diff 判定 -> 跑测试 -> 回写三分叉 -> 清理。

    参数:
      no_fix    AI 判断无从下手 -> 直接 needs-human (不看 diff)。
      diagnosis AI 的一句话诊断 (附到状态里给 owner)。
      test_runner 注入替身 (单测), 生产走真 pytest。
    """
    con = _connect(db_url)
    wt_path = pathlib.Path(worktree)
    result: dict

    try:
        # 1. AI 主动放弃 -> 转人工。
        if no_fix:
            diag = diagnosis or "AI 无从下手, 转人工"
            result = reports.mark_needs_human(con, report_id, diagnosis=diag)
            return _view(result)

        # 2. 真实 git diff 判定实际改了哪些文件 (物理护栏, 不信 AI 自报)。
        changed = _real_changed_files(wt_path)
        scope = RA.classify_scope(changed)
        if scope["verdict"] == "forbidden":
            reason = (f"{diagnosis} | {scope['reason']}" if diagnosis
                      else scope["reason"])
            result = reports.mark_needs_human(con, report_id, diagnosis=reason)
            return _view(result)

        # 3. 全低危: 落真实 diff, 跑测试。
        diff_text = _worktree_diff(wt_path)
        diff_ref = RA._persist_diff(work=_Obj(path=str(wt_path)),
                                    report_id=report_id, diff=diff_text)
        # 对口闸: 修复 Agent 只改前端展示层 (ADR-0022), 故默认验证闸是前端构建,
        # 不是全量后端 pytest (跑不到点子上 + worktree 缺未跟踪 fixture 必失败)。
        runner = test_runner or (lambda: _frontend_build(wt_path))
        passed, summary = runner()
        if passed:
            result = reports.mark_patch_ready(
                con, report_id, diff_ref=diff_ref,
                test_result=f"passed: {summary}")
        else:
            result = reports.mark_ai_failed(
                con, report_id,
                diagnosis=f"低危补丁已产出但测试未过: {summary}")
        return _view(result)
    finally:
        _cleanup_worktree(branch, wt_path)


class _Obj:
    """给 RA._persist_diff 传一个带 .path 的轻量对象。"""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _view(report: dict) -> dict:
    """finalize 回显 owner 视角 (含 diff_ref/诊断), 供 AI/日志核对落地结果。"""
    return {"report_id": report.get("id"), "status": report.get("status"),
            "diff_ref": report.get("diff_ref"),
            "test_result": report.get("test_result"),
            "diagnosis": report.get("diagnosis")}


# =========================================================================
# CLI
# =========================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="MR-C2 修复 Agent cron 运行时: claim 一条 queued 反馈, "
                    "AI 在隔离 worktree 改低危前端, finalize 收口回写状态机。")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_claim = sub.add_parser("claim", help="领走最老 queued + 建 worktree + dump 上下文")
    p_claim.add_argument("--db-url", default=None)

    p_fin = sub.add_parser("finalize", help="真实 diff 判定 + 跑测试 + 回写 + 清理")
    p_fin.add_argument("--report-id", required=True)
    p_fin.add_argument("--worktree", required=True)
    p_fin.add_argument("--branch", default=None)
    p_fin.add_argument("--db-url", default=None)
    p_fin.add_argument("--no-fix", action="store_true",
                       help="AI 无从下手, 直接转人工")
    p_fin.add_argument("--diagnosis", default="")

    args = ap.parse_args(argv)
    if args.cmd == "claim":
        out = claim(args.db_url)
    else:
        out = finalize(args.report_id, args.worktree, branch=args.branch,
                       db_url=args.db_url, no_fix=args.no_fix,
                       diagnosis=args.diagnosis)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
