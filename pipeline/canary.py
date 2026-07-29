"""MR-D (#59): 冒烟金丝雀 + 自动回滚 + 安静窗口 (PRD #54 / ADR-0023).

上线安全网 + 人工闸门收尾: owner 在反馈台批准一个 `patch-ready` 补丁后, 别直接
把未验证代码切进主进程接真实流量 —— 先在**临时端口起一个新进程**, 跑健康检查 +
冒烟(关键 API 200 / 前端可加载 / 核心页不白屏), **全过才切主进程**(旧版待命);
任一步失败**自动 `git checkout` 回上一个 good commit + 重启旧版**。检测到有
in-flight 领题/评测(assignment/submission)时, 上线动作**排到安静窗口**(或由
owner 强制), 不硬重启踹掉正在跑的评测。

单机可行档(ADR-0023): 不引流量网关、不做真·按比例分流量金丝雀 —— 拿到金丝雀
~95% 的价值(未验证代码永不接真实流量 + 失败自动回退), 留真金丝雀到多实例 v2。

分层职责(与 repair_agent 同注入式惯例: 真实现与 fake 同契约, 编排层分不出真假):
  * inflight_summary / is_quiet_window — 查 in-flight, 决定是否延迟上线(纯读, 可离线测)。
  * LocalProcess / http_health_check / git_current_commit / git_checkout /
    _switch_main / _rollback_to — 真实现(起子进程/打 HTTP/真 git), 单测注入替身。
  * run_canary — 编排: 把「批准一个补丁」安全地变成「上线 or 回滚 or 延迟」,
    并回写 MR-A 状态机(resolved / needs-human)。这是本模块立身之本。
  * approve / reject — 反馈台按钮的薄逻辑包装。

真进程重启不进单测 —— 用 canary_fakes 注入 FakeProcess / fake health / switcher /
rollbacker / notifier。决策逻辑(回滚/延迟/切换)全部可离线跑绿。

契约(编排层依赖的注入点, 生产实现与 fake 同签名):
    launcher(commit) -> 上下文管理器, __enter__ 返回有 .base_url / .port 的进程句柄。
    health_check(base_url) -> (ok: bool, detail: str)   # 健康 + 冒烟一把过
    switcher(commit, proc) -> None                       # 把主进程/tunnel 切到新版本
    rollbacker(good_commit) -> None                      # git checkout 回退 + 重启旧版
    notifier(report) -> None                             # 通知提交者「你报的问题修好上线了」
"""
from __future__ import annotations

import contextlib
import socket
import subprocess
import time
import urllib.error
import urllib.request

from pipeline import reports, store

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

# 上线前跑的冒烟探针: 关键 API 200 + 核心页不白屏。任一非 200 -> 冒烟失败 -> 回滚。
# (只读探针, 不改数据; 打到临时端口的候选进程上, 主进程不受影响。)
SMOKE_PATHS: tuple[str, ...] = (
    "/api/health",        # DB 可读(scores 计数)
    "/api/leaderboard",   # 核心数据 API
    "/",                  # 前端 index.html 能加载(SPA 根)
)


class CanaryError(reports.ReportError):
    """金丝雀上线流程的非法操作(如批准一个不在 patch-ready 的补丁)。"""


# =========================================================================
# in-flight 检测: 有活跃领题/评测就不硬重启, 排到安静窗口 (ADR-0023 闸门前置)
# =========================================================================
# 自动重启主进程会打断正在跑的评测(assignment 状态机 / in-flight submission)。
# 故上线动作若检测到活跃任务, 默认延迟到无活跃任务的安静窗口(或 owner 强制)。
# 判定只读、零副作用 —— 纯查询, 从不改状态。

def inflight_summary(con) -> dict:
    """当前有多少活跃领题/评测(决定能否安全重启)。

    活跃 = 领了还没交的活:
      - assignments 处于 'claimed'(有人领了正在做, 未提交/未放弃)。
      - assignments 处于 'submitted'(交了但流程未收口, 仍算 in-flight)。
    返回 {"claimed": n, "submitted": n, "busy": bool, "assignments": [...]}。
    """
    claimed = store.assignments_by_status(con, "claimed")
    submitted = store.assignments_by_status(con, "submitted")
    active = claimed + submitted
    return {
        "claimed": len(claimed),
        "submitted": len(submitted),
        "busy": bool(active),
        "assignments": [a.get("id") for a in active],
    }


def is_quiet_window(con) -> bool:
    """此刻是否安静窗口(无活跃领题/评测, 可安全重启主进程)。"""
    return not inflight_summary(con)["busy"]


# =========================================================================
# 真实现 helper: 起临时端口新进程 / 健康检查 / git 回滚 / 切换
# (单测一律注入替身, 这些真家伙不进 test_canary_mrd。)
# =========================================================================
def _free_port() -> int:
    """要一个空闲 TCP 端口给候选进程(金丝雀跑在临时端口, 不撞主进程 8600)。"""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalProcess:
    """在临时端口起一个候选后端进程的上下文管理器(真金丝雀载体)。

    __enter__: 在指定 commit 的代码上(调用方已 checkout 到 worktree/主树)起
    `uvicorn server.app:app --port <临时端口>`, 轮询直到 /api/health 起来。
    __exit__: 杀掉候选进程(金丝雀是一次性的, 验完即弃; 切换是另拉主进程的事)。

    契约: __enter__ 返回自身, 暴露 .base_url / .port。测试用 FakeProcess 替身,
    不真 fork uvicorn。
    """

    def __init__(self, *, cwd: str | None = None, port: int | None = None,
                 boot_timeout: float = 30.0):
        self.cwd = cwd or str(ROOT)
        self.port = port or _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.boot_timeout = boot_timeout
        self._proc: subprocess.Popen | None = None

    def __enter__(self) -> "LocalProcess":
        self._proc = subprocess.Popen(
            ["python", "-m", "uvicorn", "server.app:app",
             "--host", "127.0.0.1", "--port", str(self.port),
             "--log-level", "warning"],
            cwd=self.cwd)
        deadline = time.time() + self.boot_timeout
        while time.time() < deadline:
            ok, _ = http_health_check(self.base_url, paths=("/api/health",))
            if ok:
                return self
            time.sleep(0.5)
        # 起不来也返回(健康检查会在 run_canary 里判失败 -> 回滚), 但先别泄漏进程。
        return self

    def __exit__(self, *exc) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()


def http_health_check(base_url: str, *, paths: tuple[str, ...] = SMOKE_PATHS,
                      timeout: float = 5.0) -> tuple[bool, str]:
    """对候选进程跑健康检查 + 冒烟: 每个关键路径必须 HTTP 200。

    任一路径非 200 / 连不上 -> (False, 失败原因)。全过 -> (True, 摘要)。
    只读探针, 不改数据。真实现; 单测注入 fake health check。
    """
    for p in paths:
        url = f"{base_url}{p}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                code = resp.getcode()
            if code != 200:
                return False, f"冒烟失败: {p} 返回 {code}(期望 200)"
        except urllib.error.HTTPError as e:
            return False, f"冒烟失败: {p} HTTP {e.code}"
        except Exception as e:
            return False, f"冒烟失败: {p} 连不上({e})"
    return True, f"冒烟通过: {len(paths)} 个关键路径全 200"


def git_current_commit(cwd: str | None = None) -> str:
    """当前 HEAD 的 commit(上线前抓, 作为金丝雀失败时的回滚锚点 good_commit)。"""
    out = subprocess.run(["git", "rev-parse", "HEAD"],
                         cwd=cwd or str(ROOT), capture_output=True, text=True)
    if out.returncode != 0:
        raise CanaryError(f"取当前 commit 失败: {out.stderr.strip()}")
    return out.stdout.strip()


def git_checkout(commit: str, cwd: str | None = None) -> None:
    """把工作树 checkout 回指定 commit(回滚锚点)。真 git 操作。"""
    out = subprocess.run(["git", "checkout", commit],
                         cwd=cwd or str(ROOT), capture_output=True, text=True)
    if out.returncode != 0:
        raise CanaryError(f"git checkout {commit} 失败: {out.stderr.strip()}")


def _default_rollbacker(good_commit: str) -> None:
    """真回滚: git checkout 回上一个 good commit(重启旧版由外部进程守护接管)。

    单机档: 主进程/tunnel 由 run_frontend.sh / supervisor 守护, checkout 回退后
    重启即拉起旧版本。测试注入 fake, 不真 checkout。
    """
    git_checkout(good_commit)


# =========================================================================
# 编排: 把「owner 批准一个补丁」安全变成「上线 / 回滚 / 延迟」+ 回写状态机
# =========================================================================
def run_canary(con, report_id: str, *,
               launcher=None, health_check=None, switcher=None,
               rollbacker=None, notifier=None,
               good_commit: str | None = None,
               allow_when_busy: bool = False,
               now: float | None = None) -> dict:
    """owner 批准一个 patch-ready 补丁后的上线安全网 (ADR-0023)。

    流程:
      0. 守卫: 只有 patch-ready 可上线; 否则 CanaryError(不静默)。
      1. in-flight 闸门: 有活跃领题/评测且未 allow_when_busy -> 不动主进程,
         report 仍停在 patch-ready, 返回 {"outcome": "deferred", ...}
         (排到安静窗口 / 让 owner 确认后强制)。
      2. 抓 good_commit(回滚锚点)—— 显式传入优先, 否则取当前 HEAD。
      3. 临时端口起候选进程(launcher 上下文), 跑健康检查 + 冒烟。
         - 任一步失败 -> rollbacker(good_commit) 回退旧版, report -> needs-human
           (附失败原因), switcher **绝不**被调(坏代码不接真实流量),
           返回 {"outcome": "rolled-back", ...}。
         - 全过 -> switcher(commit, proc) 切主进程, report -> resolved
           (记 good_commit + resolved_ts), notifier 通知提交者,
           返回 {"outcome": "resolved", ...}。

    真进程/真 git 由默认实现兜底; 单测注入 canary_fakes 的替身, 决策逻辑离线跑绿。
    """
    t = now if now is not None else time.time()
    r = reports.get(con, report_id)
    if r["status"] != "patch-ready":
        raise CanaryError(
            f"run_canary 只上线 patch-ready 的补丁, 当前 {r['status']!r}")

    # 1. in-flight 闸门: 不硬重启踹掉正在跑的评测。
    flight = inflight_summary(con)
    if flight["busy"] and not allow_when_busy:
        return {"outcome": "deferred", "report": r, "inflight": flight,
                "reason": (f"检测到 {flight['claimed']} 个领题 / "
                           f"{flight['submitted']} 个待收口评测正在进行, "
                           f"上线延迟到安静窗口(或 owner 确认强制)")}

    # 2. 回滚锚点。
    gc = good_commit
    if gc is None:
        try:
            gc = git_current_commit()
        except CanaryError:
            gc = None  # 非 git 环境(测试)也能跑决策逻辑

    hc = health_check or (lambda base: http_health_check(base))
    rb = rollbacker or _default_rollbacker
    make_proc = launcher or (lambda: LocalProcess())

    # 3. 临时端口起候选进程 -> 健康 + 冒烟。
    proc = make_proc()
    with proc as candidate:
        base = getattr(candidate, "base_url", "http://127.0.0.1:0")
        ok, detail = hc(base)
        if not ok:
            # 失败: 回滚旧版, 转人工, switcher 绝不被调。
            if gc is not None:
                rb(gc)
            updated = reports.mark_needs_human(
                con, report_id,
                diagnosis=f"金丝雀失败自动回滚(回退到 {gc}): {detail}")
            return {"outcome": "rolled-back", "report": updated,
                    "good_commit": gc, "detail": detail}

        # 全过: 切主进程 -> resolved -> 通知提交者。
        if switcher is not None:
            switcher(gc, candidate)

    updated = reports.resolve(con, report_id, good_commit=gc, now=t)
    if notifier is not None:
        notifier(updated)
    return {"outcome": "resolved", "report": updated,
            "good_commit": gc, "detail": detail}


# =========================================================================
# 反馈台按钮的薄逻辑: 批准(走金丝雀)/ 拒绝(转人工, 可留言让 AI 重试)
# =========================================================================
def approve(con, report_id: str, *, allow_when_busy: bool = False,
            **canary_kw) -> dict:
    """owner 一键批准: 走冒烟金丝雀上线(run_canary 薄包装, story 17/18/19)。"""
    return run_canary(con, report_id, allow_when_busy=allow_when_busy,
                      **canary_kw)


def reject(con, report_id: str, *, message: str | None = None,
           retry: bool = False, now: float | None = None) -> dict:
    """owner 拒绝一个 patch-ready 补丁 (story 16)。

    - 先落 needs-human(附 owner 留言作诊断), 与金丝雀失败回滚共用同一枢纽态。
    - retry=True: 再把它 enqueue 回 queued, 让修复 Agent 按留言重试一次。
    否则停在 needs-human 等人工处理。返回落地后的 report 行。
    """
    r = reports.get(con, report_id)
    if r["status"] != "patch-ready":
        raise CanaryError(
            f"reject 只作用于 patch-ready 的补丁, 当前 {r['status']!r}")
    diag = message or "owner 拒绝了该补丁"
    updated = reports.mark_needs_human(con, report_id, diagnosis=diag, now=now)
    if retry:
        updated = reports.enqueue(con, report_id, now=now)
    return updated
