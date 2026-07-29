"""MR-C (#57): 修复 Agent 的离线 fake 替身 (prior art: intake_fakes / review_fakes).

单测不真调 AI、不真 fork git worktree、不真跑 pytest。本模块提供:
  * make_fake_agent — 一个吃 prompt dict、吐固定结果 dict 的假 agent, 完全离线、
    确定性。它与真 agent (violoop heavy 档) 同契约, 驱动层 (run_repair) 分不出真假。
  * FakeWorktree — GitWorktree 的替身: 不 fork 进程、不建工作树, 只记录「进出过」
    供测试断言隔离 (Agent 只在 worktree 上下文内被驱动)。
  * make_fake_test_runner — 假测试执行器, 直接返回 (passed, summary), 不起子进程。

真实现与 fake 同契约: 生产路径用真 agent + GitWorktree + _run_tests; 测试路径注入
这里的替身。契约见 repair_agent.build_prompt / run_repair 的 agent 说明。
"""
from __future__ import annotations


def make_fake_agent(*, changed_files=None, diff: str = "--- a\n+++ b\n",
                    diagnosis: str = "fake 诊断: 前端展示层问题",
                    no_fix: bool = False):
    """返回一个忽略 prompt 内容、吐固定结果的假 agent。

    默认: 改一个低危页面文件, 给一段假 diff。用参数造各种分支场景:
      - changed_files=["pipeline/auth.py"] -> 触碰禁区, 驱动层应转 needs-human。
      - no_fix=True                        -> agent 放弃, 驱动层应转 needs-human。
      - changed_files=["frontend/src/pages/X.jsx"] -> 低危, 视测试结果 -> patch-ready/ai-failed。
    """
    files = changed_files if changed_files is not None else [
        "frontend/src/pages/Leaderboard.jsx"]

    def _agent(prompt: dict) -> dict:
        # 记一手收到的 prompt, 方便测试断言多模态上下文确实拼进来了。
        _agent.last_prompt = prompt
        return {
            "changed_files": list(files),
            "diff": diff,
            "diagnosis": diagnosis,
            "no_fix": no_fix,
        }

    _agent.last_prompt = None
    return _agent


class FakeWorktree:
    """GitWorktree 的离线替身: 不 fork、不建工作树, 只记录进出与是否隔离。

    契约同 GitWorktree: __enter__ 返回有 .path / .branch 的对象。测试可断言
    entered/exited 来证明「Agent 只在 worktree 上下文内被驱动」(隔离成立)。
    """

    def __init__(self, *, branch: str = "repair/ur-fake0001",
                 path: str = "/tmp/fake-worktree"):
        self.branch = branch
        self.path = path
        self.entered = False
        self.exited = False

    def __enter__(self) -> "FakeWorktree":
        self.entered = True
        return self

    def __exit__(self, *exc) -> None:
        self.exited = True


def make_fake_test_runner(*, passed: bool = True, summary: str = "3 passed"):
    """返回一个假测试执行器 () -> (passed, summary), 不起子进程。"""
    def _runner():
        return passed, summary
    return _runner


__all__ = [
    "make_fake_agent", "FakeWorktree", "make_fake_test_runner",
]
