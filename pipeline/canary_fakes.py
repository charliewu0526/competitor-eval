"""MR-D (#59): 冒烟金丝雀的离线 fake 替身 (prior art: repair_fakes / intake_fakes).

单测不真 fork uvicorn、不真 git checkout、不真打 HTTP。本模块提供 run_canary 的
全套注入替身, 让上线决策逻辑(切换 / 回滚 / 延迟)完全离线、确定性地跑绿:

  * FakeProcess       — LocalProcess 的替身: 不 fork 进程, 只记 started/stopped,
                        暴露 .base_url / .port 供编排层拿去做健康检查。
  * make_fake_health_check — 造健康检查结果: ok=True 造冒烟通过; ok=False +
                        detail 造冒烟失败(编排层应据此回滚)。
  * make_fake_switcher — 记录「切主进程」被调与传入的 commit / 进程句柄。
  * make_fake_rollbacker — 记录「回滚」被调与回退到的 good_commit。
  * make_fake_notifier — 记录通知了哪条 report / 哪个 submitter。

真实现与 fake 同契约(见 canary.run_canary 的注入点说明): 生产路径用真
LocalProcess + http_health_check + _switch_main + _default_rollbacker; 测试路径
注入这里的替身。
"""
from __future__ import annotations


class FakeProcess:
    """LocalProcess 的离线替身: 不 fork uvicorn, 只记录进出与暴露 base_url。

    契约同 LocalProcess: __enter__ 返回有 .base_url / .port 的对象。测试可断言
    started/stopped 证明「候选进程确实被起过又被收掉」(金丝雀是一次性的)。
    """

    def __init__(self, *, port: int = 8799,
                 base_url: str | None = None):
        self.port = port
        self.base_url = base_url or f"http://127.0.0.1:{port}"
        self.started = False
        self.stopped = False

    def __enter__(self) -> "FakeProcess":
        self.started = True
        return self

    def __exit__(self, *exc) -> None:
        self.stopped = True


def make_fake_health_check(*, ok: bool = True,
                           detail: str | None = None):
    """返回一个假健康检查 (base_url) -> (ok, detail), 不真打 HTTP。

    - ok=True  -> 冒烟通过, 编排层应切主进程 -> resolved。
    - ok=False -> 冒烟失败, 编排层应回滚 -> needs-human。
    记录 last_base_url 供测试断言「确实探了候选进程而非主进程」。
    """
    d = detail or ("冒烟通过: fake" if ok else "冒烟失败: fake 关键 API 非 200")

    def _check(base_url: str):
        _check.last_base_url = base_url
        _check.calls += 1
        return ok, d

    _check.last_base_url = None
    _check.calls = 0
    return _check


def make_fake_switcher():
    """返回一个假 switcher (commit, proc) -> None, 记录被调与参数。

    切主进程只在冒烟通过后被调 —— 测试用 .calls / .commit 断言坏补丁绝不切流量。
    """
    def _switch(commit, proc):
        _switch.calls += 1
        _switch.commit = commit
        _switch.proc = proc

    _switch.calls = 0
    _switch.commit = None
    _switch.proc = None
    return _switch


def make_fake_rollbacker():
    """返回一个假 rollbacker (good_commit) -> None, 记录回退锚点。

    只在健康/冒烟失败时被调 —— 测试用 .calls / .good_commit 断言失败即回滚。
    """
    def _rollback(good_commit):
        _rollback.calls += 1
        _rollback.good_commit = good_commit

    _rollback.calls = 0
    _rollback.good_commit = None
    return _rollback


def make_fake_notifier():
    """返回一个假 notifier (report) -> None, 记录通知了哪条 report / submitter。

    只在上线成功(resolved)后被调 —— 测试断言提交者收到「你报的问题修好上线了」。
    """
    def _notify(report):
        _notify.calls += 1
        _notify.reports.append(report)
        _notify.submitters.append((report or {}).get("submitter"))

    _notify.calls = 0
    _notify.reports = []
    _notify.submitters = []
    return _notify


def fake_launcher(proc: FakeProcess):
    """把一个 FakeProcess 包成 run_canary 期望的 launcher() -> 上下文管理器。"""
    def _make():
        return proc
    return _make


__all__ = [
    "FakeProcess", "make_fake_health_check", "make_fake_switcher",
    "make_fake_rollbacker", "make_fake_notifier", "fake_launcher",
]
