"""MR-C2 (#58): repair_runner cron 运行时装配的离线单测.

验证外部行为 (不真调 AI, 用真临时 git 仓 + 注入 test_runner):
  AC1  claim 原子领走最老 queued -> ai-working, 建隔离 worktree, dump 上下文文件。
  AC2  finalize 用**真实 git diff** 判定实际改动 (信 git 不信 AI 自报):
         改低危前端文件 + 测试过 -> patch-ready (带真实 diff_ref/test_result)。
         改硬禁区文件         -> needs-human (绝不自动上, 丢弃改动)。
         无任何改动           -> needs-human。
         低危改动但测试挂      -> ai-failed。
  AC3  no_fix -> needs-human, 不看 diff。
  AC4  并发: 队列空时 claim 返回 {report_id: None}; 领完再 claim 空领。
  AC5  finalize 后 worktree 被清理, 主工作树不被污染。

抗注入要点 (与 MR-C 单测的关键区别): 这里**不注入 changed_files**, 而是真的在
worktree 里改文件, 让 finalize 跑真 git diff 判定 —— 证明护栏基于物理落盘的文件路径。

Run: python -m pytest tests/test_repair_runner_mrc2.py -q
"""
from __future__ import annotations
import json
import pathlib
import subprocess
import tempfile
import unittest

from pipeline import store
from pipeline import reports as R
from pipeline import repair_agent as RA
from pipeline import repair_runner as RUN


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def _make_repo() -> pathlib.Path:
    """建一个真临时 git 仓, 含一个低危前端文件 + 一个硬禁区文件, 一个初始 commit。"""
    root = pathlib.Path(tempfile.mkdtemp(prefix="mrc2-repo-"))
    (root / "frontend" / "src" / "pages").mkdir(parents=True)
    (root / "pipeline").mkdir(parents=True)
    (root / "frontend" / "src" / "pages" / "Leaderboard.jsx").write_text(
        "export default function Leaderboard(){ return <div>board</div>; }\n")
    (root / "pipeline" / "auth.py").write_text("# 鉴权模块 (硬禁区)\nSECRET = 1\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


class _Case(unittest.TestCase):
    """公共夹具: 每个用例一个独立 git 仓 + SQLite 库 + 一条 queued report。"""

    def setUp(self):
        self.repo = _make_repo()
        self.db = str(pathlib.Path(tempfile.mkdtemp()) / "t.db")
        self.con = store.connect(self.db)

    def _queued(self, text="看板页白屏了"):
        r = R.create(self.con, "u1", text)
        R.enqueue(self.con, r["id"])
        return r["id"]

    def _worktree_factory(self):
        """一个 0 参工厂: 每次调用造一个落在**本用例临时仓**里的 GitWorktree。"""
        return lambda: RA.GitWorktree(root=self.repo)

    def _claim(self):
        """claim 一条 (指向临时仓 + 临时库)。返回 claim 的 dict。"""
        # RUN.claim 内部默认用 RA.GitWorktree(root=ROOT=真项目仓); 这里注入
        # worktree_factory 指向本用例临时仓, db_url 指向临时库, 全程不碰真项目。
        return RUN.claim(self.db, worktree_factory=self._worktree_factory())

    # ---- AC1: claim 领走 + 建 worktree + dump 上下文 --------------------
    def test_claim_moves_to_ai_working_and_dumps_context(self):
        rid = self._queued()
        out = self._claim()
        self.assertEqual(out["report_id"], rid)
        self.assertIsNotNone(out["worktree"])
        # 状态推进到 ai-working, 记了分支。
        row = R.get(self.con, rid)
        self.assertEqual(row["status"], "ai-working")
        self.assertEqual(row["branch_name"], out["branch"])
        # 上下文文件真落到 worktree, 内容含反馈文字 + 作用域约束。
        ctx = json.loads(pathlib.Path(out["context_file"]).read_text(encoding="utf-8"))
        self.assertEqual(ctx["report_id"], rid)
        self.assertIn("白屏", ctx["text"])
        self.assertIn("低危", ctx["scope_instruction"])

    # ---- AC4: 队列空 / 领完再领 -> 空领取 -----------------------------
    def test_claim_empty_queue_returns_none(self):
        self.assertEqual(RUN.claim(self.db)["report_id"], None)

    def test_claim_twice_second_is_empty(self):
        self._queued()
        first = self._claim()
        self.assertIsNotNone(first["report_id"])
        # 唯一那条已被领走 (ai-working), 队列里没有 queued 了。
        self.assertEqual(self._claim()["report_id"], None)
        RUN._cleanup_worktree(first["branch"], pathlib.Path(first["worktree"]))

    # ---- finalize 三分叉: 全部基于**真实 git diff** 判定 (不注入 changed_files) --
    def _edit(self, worktree, relpath, content):
        """在 worktree 里真的改/加一个文件, 模拟 AI 落盘 (finalize 靠 git 看见它)。"""
        p = pathlib.Path(worktree) / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def _fin(self, rid, out, **kw):
        kw.setdefault("branch", out["branch"])
        return RUN.finalize(rid, out["worktree"], db_url=self.db, **kw)

    # AC2-a: 改低危前端文件 + 测试过 -> patch-ready, 带真实 diff_ref/test_result。
    def test_finalize_lowrisk_pass_to_patch_ready(self):
        rid = self._queued()
        out = self._claim()
        self._edit(out["worktree"], "frontend/src/pages/Leaderboard.jsx",
                   "export default function Leaderboard(){ return <div>fixed</div>; }\n")
        fin = self._fin(rid, out, test_runner=lambda: (True, "3 passed"),
                        diagnosis="把榜单空态文案改成人话")
        self.assertEqual(fin["status"], "patch-ready")
        self.assertIsNotNone(fin["diff_ref"])
        self.assertTrue(pathlib.Path(fin["diff_ref"]).read_text().strip())
        row = R.get(self.con, rid)
        self.assertEqual(row["status"], "patch-ready")
        # AI 修复 == 提 PR: patch_summary 是给 owner 审的「PR 描述」,须含 AI 的
        # 修复说明 + 真实改动文件清单(信 git),owner 据此判断修法对不对。
        summary = row["patch_summary"]
        self.assertIsNotNone(summary)
        self.assertIn("把榜单空态文案改成人话", summary)
        self.assertIn("Leaderboard.jsx", summary)
        self.assertIn("改动规模", summary)
        # worktree 被清理, 主临时仓工作树干净 (未污染)。
        self.assertFalse(pathlib.Path(out["worktree"]).exists())
        self.assertEqual(_git(self.repo, "status", "--porcelain").stdout, "")

    # AC2-b: 改硬禁区文件 -> needs-human, 绝不自动上 (即便测试会过也不跑到那步)。
    def test_finalize_forbidden_file_to_needs_human(self):
        rid = self._queued()
        out = self._claim()
        # AI 偷改鉴权 (硬禁区)。finalize 看真实 diff 就该拦下。
        self._edit(out["worktree"], "pipeline/auth.py", "# 被改过\nSECRET = 999\n")
        called = {"ran": False}
        def _runner():
            called["ran"] = True
            return (True, "should not run")
        fin = self._fin(rid, out, test_runner=_runner)
        self.assertEqual(fin["status"], "needs-human")
        self.assertFalse(called["ran"], "禁区改动绝不该跑到测试/落 diff")
        self.assertIn("禁区", fin["diagnosis"])

    # AC2-c: 无任何改动 -> needs-human (空改动 fail closed)。
    def test_finalize_no_change_to_needs_human(self):
        rid = self._queued()
        out = self._claim()
        fin = self._fin(rid, out, test_runner=lambda: (True, "x"))
        self.assertEqual(fin["status"], "needs-human")

    # AC2-d: 低危改动但测试挂 -> ai-failed。
    def test_finalize_lowrisk_test_fail_to_ai_failed(self):
        rid = self._queued()
        out = self._claim()
        self._edit(out["worktree"], "frontend/src/pages/Leaderboard.jsx",
                   "// broken\n")
        fin = self._fin(rid, out, test_runner=lambda: (False, "1 failed"))
        self.assertEqual(fin["status"], "ai-failed")

    # AC3: no_fix -> needs-human, 不看 diff。
    def test_finalize_no_fix_to_needs_human(self):
        rid = self._queued()
        out = self._claim()
        # 即便 worktree 里有低危改动, no_fix 也直接转人工。
        self._edit(out["worktree"], "frontend/src/pages/Leaderboard.jsx", "// x\n")
        fin = self._fin(rid, out, no_fix=True, diagnosis="超出前端范畴")
        self.assertEqual(fin["status"], "needs-human")
        self.assertIn("超出前端", fin["diagnosis"])


if __name__ == "__main__":
    unittest.main()
