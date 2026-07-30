"""MR-C (#57): 修复 Agent 逻辑 + 低危白名单/硬禁区 + repair_fakes.

验证外部行为 (prior art: test_intake_seam_mr2 的 fakes 注入):
  AC1  给定 queued report + 假 agent, 驱动出候选 diff 并跑测试, 结果回写
       patch-ready / needs-human / ai-failed。
  AC2  低危白名单命中 + 硬禁区拦截判定被测试锁死 (碰禁区 -> needs-human, 绝不自动改)。
  AC3  Agent 工作在隔离 worktree, 不污染主工作树 (FakeWorktree 断言隔离)。
  AC4  owner 见 diff/测试/诊断; 提交者侧不可见 (strip_repair_fields / view_for)。
  AC5  单测不真调 AI (repair_fakes 注入), 纯逻辑离线跑绿。

Run: python -m unittest tests.test_repair_agent_mrc -v
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import store
from pipeline import reports as R
from pipeline import repair_agent as RA
from pipeline import repair_fakes as RF


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


def _queued(con, text="看板页白屏了"):
    r = R.create(con, "u1", text)
    R.enqueue(con, r["id"])
    return r["id"]


# ---------------------------------------------------------------------------
# AC2: 作用域判定 (纯函数, 不碰 DB) —— 全模块立身之本
# ---------------------------------------------------------------------------
class ScopeClassification(unittest.TestCase):
    def test_lowrisk_files_pass(self):
        for f in ("frontend/src/pages/Leaderboard.jsx",
                  "frontend/src/components/Chart.jsx",
                  "frontend/src/index.css",
                  "frontend/src/glossary.jsx",
                  # 放宽 (2026-07-30): 前端展示层整体低危 —— App.jsx(根布局/路由/菜单)、
                  # main.jsx(入口)、api.js(前端请求封装)不再是灰区。
                  "frontend/src/App.jsx",
                  "frontend/src/main.jsx",
                  "frontend/src/api.js"):
            self.assertTrue(RA.is_low_risk(f), f)
            self.assertFalse(RA.is_forbidden(f), f)

    def test_frontend_auth_still_forbidden_after_loosening(self):
        # 放宽白名单后仍须守住: auth.jsx 是鉴权入口, 禁区优先级高于低危白名单,
        # 绝不因"前端展示层整体低危"而被放行。
        self.assertTrue(RA.is_forbidden("frontend/src/auth.jsx"))
        self.assertFalse(RA.is_low_risk("frontend/src/auth.jsx"))
        v = RA.classify_scope(["frontend/src/App.jsx", "frontend/src/auth.jsx"])
        self.assertEqual(v["verdict"], "forbidden")   # 混入鉴权文件 -> 整批拒

    def test_forbidden_files_blocked(self):
        for f in ("pipeline/auth.py", "pipeline/rbac.py",
                  "pipeline/store.py", "pipeline/logview.py",
                  "pipeline/artifact_store.py", "pipeline/authorize.py",
                  "frontend/src/auth.jsx",
                  ".env", "deploy/rollout.sh", "scripts/serve_backend.sh",
                  "config/secret_key.pem", "Dockerfile",
                  ".github/workflows/ci.yml",
                  "migrations/003_add_col.sql"):
            self.assertTrue(RA.is_forbidden(f), f)
            self.assertFalse(RA.is_low_risk(f), f)

    def test_verdict_lowrisk_when_all_whitelisted(self):
        v = RA.classify_scope(["frontend/src/pages/A.jsx",
                               "frontend/src/index.css"])
        self.assertEqual(v["verdict"], "low-risk")

    def test_verdict_forbidden_if_any_forbidden(self):
        # 一颗老鼠屎: 混一个禁区文件 -> 整批 forbidden。
        v = RA.classify_scope(["frontend/src/pages/A.jsx", "pipeline/auth.py"])
        self.assertEqual(v["verdict"], "forbidden")
        self.assertIn("pipeline/auth.py", v["forbidden"])

    def test_gray_area_fails_closed(self):
        # 既非白名单也非禁区 (后端非敏感文件) -> 未知即拒。
        v = RA.classify_scope(["pipeline/leaderboard.py"])
        self.assertEqual(v["verdict"], "forbidden")
        self.assertIn("pipeline/leaderboard.py", v["gray"])

    def test_empty_changes_fail_closed(self):
        v = RA.classify_scope([])
        self.assertEqual(v["verdict"], "forbidden")


# ---------------------------------------------------------------------------
# AC1 + AC3 + AC5: 驱动假 agent -> 回写状态机, 隔离 worktree, 全离线
# ---------------------------------------------------------------------------
class DriveRepair(unittest.TestCase):
    def _run(self, con, rid, agent, *, passed=True):
        wt = RF.FakeWorktree()
        self._wt = wt
        return RA.run_repair(
            con, rid, agent,
            worktree_factory=lambda: wt,
            test_runner=RF.make_fake_test_runner(passed=passed))

    def test_lowrisk_tests_pass_to_patch_ready(self):
        con = store.connect(_tmpdb())
        rid = _queued(con)
        agent = RF.make_fake_agent(
            changed_files=["frontend/src/pages/Leaderboard.jsx"])
        row = self._run(con, rid, agent, passed=True)
        self.assertEqual(row["status"], "patch-ready")
        self.assertIsNotNone(row["diff_ref"])
        self.assertIn("passed", row["test_result"])
        # AC3: worktree 进出过 (隔离成立)。
        self.assertTrue(self._wt.entered and self._wt.exited)
        # branch 记进 report。
        self.assertEqual(row["branch_name"], self._wt.branch)

    def test_lowrisk_tests_fail_to_ai_failed(self):
        con = store.connect(_tmpdb())
        rid = _queued(con)
        agent = RF.make_fake_agent(
            changed_files=["frontend/src/pages/Cost.jsx"])
        row = self._run(con, rid, agent, passed=False)
        self.assertEqual(row["status"], "ai-failed")
        self.assertIn("测试未过", row["diagnosis"])

    def test_forbidden_scope_to_needs_human(self):
        con = store.connect(_tmpdb())
        rid = _queued(con)
        agent = RF.make_fake_agent(changed_files=["pipeline/auth.py"])
        row = self._run(con, rid, agent, passed=True)
        # 碰禁区 -> 绝不自动改, 转人工附原因。
        self.assertEqual(row["status"], "needs-human")
        self.assertIn("禁区", row["diagnosis"])

    def test_agent_gives_up_to_needs_human(self):
        con = store.connect(_tmpdb())
        rid = _queued(con)
        agent = RF.make_fake_agent(no_fix=True, diagnosis="无从下手")
        row = self._run(con, rid, agent, passed=True)
        self.assertEqual(row["status"], "needs-human")
        self.assertEqual(row["diagnosis"], "无从下手")

    def test_forbidden_never_runs_tests_nor_writes_diff(self):
        # 碰禁区必须在跑测试/落 diff 之前就拦下 (物理边界优先)。
        con = store.connect(_tmpdb())
        rid = _queued(con)
        ran = {"tests": False}

        def _tripwire():
            ran["tests"] = True
            return True, "should not run"

        wt = RF.FakeWorktree()
        agent = RF.make_fake_agent(changed_files=["pipeline/store.py"])
        row = RA.run_repair(con, rid, agent, worktree_factory=lambda: wt,
                            test_runner=_tripwire)
        self.assertEqual(row["status"], "needs-human")
        self.assertFalse(ran["tests"], "禁区改动绝不应跑测试")
        self.assertIsNone(row["diff_ref"], "禁区改动绝不应落 diff")

    def test_only_queued_can_be_driven(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")  # submitted, 未入队
        agent = RF.make_fake_agent()
        with self.assertRaises(R.ReportError):
            RA.run_repair(con, r["id"], agent,
                          worktree_factory=lambda: RF.FakeWorktree(),
                          test_runner=RF.make_fake_test_runner())

    def test_prompt_carries_multimodal_context(self):
        con = store.connect(_tmpdb())
        rid = _queued(con, text="点导出没反应")
        agent = RF.make_fake_agent(
            changed_files=["frontend/src/pages/GapReport.jsx"])
        self._run(con, rid, agent, passed=True)
        p = agent.last_prompt
        self.assertEqual(p["text"], "点导出没反应")
        self.assertIn("低危", p["scope_instruction"])


# ---------------------------------------------------------------------------
# AC1 (build_prompt) — 多模态上下文拼装
# ---------------------------------------------------------------------------
class BuildPrompt(unittest.TestCase):
    def test_assembles_all_modalities(self):
        report = {"id": "ur-1", "text": "白屏", "submitter": "u1"}
        p = RA.build_prompt(
            report,
            screenshots=["/srv/shot1.png", "/srv/shot2.png"],
            log_excerpt="Traceback ...",
            source_files=[("frontend/src/pages/A.jsx", "export default ...")])
        self.assertEqual(p["report_id"], "ur-1")
        self.assertEqual(p["text"], "白屏")
        self.assertEqual(len(p["screenshots"]), 2)
        self.assertIn("Traceback", p["log_excerpt"])
        self.assertEqual(len(p["source_files"]), 1)
        self.assertIn("严禁", p["scope_instruction"])


# ---------------------------------------------------------------------------
# AC4: owner 可见 diff/诊断/测试; 提交者不可见
# ---------------------------------------------------------------------------
class OwnerOnlyVisibility(unittest.TestCase):
    def _resolved_row(self):
        con = store.connect(_tmpdb())
        rid = _queued(con)
        agent = RF.make_fake_agent(
            changed_files=["frontend/src/pages/Leaderboard.jsx"])
        row = RA.run_repair(
            con, rid, agent, worktree_factory=lambda: RF.FakeWorktree(),
            test_runner=RF.make_fake_test_runner(passed=True))
        return row

    def test_submitter_view_hides_internal_fields(self):
        row = self._resolved_row()
        stripped = RA.strip_repair_fields(row)
        for f in ("diff_ref", "diagnosis", "test_result", "branch_name",
                  "good_commit"):
            self.assertNotIn(f, stripped, f)
        # 提交者仍看得到进展。
        self.assertEqual(stripped["status"], "patch-ready")
        self.assertIn("id", stripped)
        self.assertIn("text", stripped)

    def test_owner_view_keeps_internal_fields(self):
        row = self._resolved_row()
        owner = RA.view_for(row, role="owner")
        self.assertIn("diff_ref", owner)
        self.assertIsNotNone(owner["diff_ref"])

    def test_non_owner_view_stripped(self):
        row = self._resolved_row()
        for role in ("intern", "reviewer", None):
            v = RA.view_for(row, role=role)
            self.assertNotIn("diff_ref", v, role)
            self.assertNotIn("diagnosis", v, role)


if __name__ == "__main__":
    unittest.main()
