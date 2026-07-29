"""MR-D (#59): 冒烟金丝雀 + 自动回滚 + 安静窗口 + 批准/拒绝.

验证外部行为, 不验实现细节 (prior art: test_repair_agent_mrc / test_health_pg_fixes_mr14):
  * 只有 patch-ready 的补丁可上线/批准 (其它态守卫 -> CanaryError)。
  * 冒烟通过 -> switcher 切主进程 + report -> resolved + good_commit 记入 +
    notifier 通知提交者。
  * 健康/冒烟失败 -> rollbacker 回退到 good_commit + report -> needs-human
    (诊断含失败原因) + switcher **绝不**被调 (坏代码不接真实流量)。
  * in-flight (有 claimed/submitted assignment) -> run_canary 延迟 (deferred),
    report 仍停在 patch-ready, 候选进程都不起; allow_when_busy=True 才照跑。
  * reject -> needs-human 附 owner 留言; retry=True -> 再 enqueue 回 queued。
  * inflight_summary / is_quiet_window 计数正确。

真进程重启/真 git 不进单测 —— 全 OFFLINE 注入 canary_fakes 的替身。

Run: python -m pytest tests/test_canary_mrd.py -q
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import store
from pipeline import reports as R
from pipeline import canary as C
from pipeline import canary_fakes as CF


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


def _patch_ready(con, submitter="alice", text="看板白屏"):
    """造一条走到 patch-ready 的 report (模拟 MR-C 干完等 owner 审的样子)。"""
    r = R.create(con, submitter, text)
    rid = r["id"]
    R.enqueue(con, rid)
    R.start_ai(con, rid, branch_name="repair/ur-x")
    R.mark_patch_ready(con, rid, diff_ref="/uploads/reports/x/diff.patch",
                       test_result="3 passed")
    return rid


# =============================================================================
# in-flight 检测: 有活跃领题/评测就不硬重启
# =============================================================================
class InflightDetection(unittest.TestCase):
    def test_quiet_window_when_no_active_assignments(self):
        con = store.connect(_tmpdb())
        self.assertTrue(C.is_quiet_window(con))
        s = C.inflight_summary(con)
        self.assertFalse(s["busy"])
        self.assertEqual(s["claimed"], 0)
        self.assertEqual(s["submitted"], 0)

    def test_claimed_assignment_counts_as_busy(self):
        con = store.connect(_tmpdb())
        store.upsert_assignment(con, {"id": "a1", "task_id": "T1",
                                      "products": ["vio"], "status": "open"})
        self.assertTrue(store.claim_assignment(con, "a1", "runner1"))
        self.assertFalse(C.is_quiet_window(con))
        s = C.inflight_summary(con)
        self.assertTrue(s["busy"])
        self.assertEqual(s["claimed"], 1)
        self.assertIn("a1", s["assignments"])

    def test_submitted_assignment_still_inflight(self):
        con = store.connect(_tmpdb())
        store.upsert_assignment(con, {"id": "a2", "task_id": "T1",
                                      "products": ["vio"], "status": "submitted"})
        s = C.inflight_summary(con)
        self.assertTrue(s["busy"])
        self.assertEqual(s["submitted"], 1)


# =============================================================================
# run_canary 状态守卫
# =============================================================================
class OnlyPatchReadyCanGoLive(unittest.TestCase):
    def test_non_patch_ready_rejected(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "alice", "x")           # submitted
        with self.assertRaises(C.CanaryError):
            C.run_canary(con, r["id"],
                         launcher=CF.fake_launcher(CF.FakeProcess()),
                         health_check=CF.make_fake_health_check(ok=True))

    def test_queued_cannot_be_approved(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "alice", "x")
        R.enqueue(con, r["id"])                    # queued
        with self.assertRaises(C.CanaryError):
            C.approve(con, r["id"],
                      launcher=CF.fake_launcher(CF.FakeProcess()),
                      health_check=CF.make_fake_health_check(ok=True))


# =============================================================================
# 冒烟通过 -> 切主进程 -> resolved -> 通知提交者
# =============================================================================
class SmokePassSwitchesAndResolves(unittest.TestCase):
    def test_pass_switches_resolves_and_notifies(self):
        con = store.connect(_tmpdb())
        rid = _patch_ready(con, submitter="alice")
        proc = CF.FakeProcess()
        hc = CF.make_fake_health_check(ok=True)
        sw = CF.make_fake_switcher()
        rb = CF.make_fake_rollbacker()
        nt = CF.make_fake_notifier()

        out = C.run_canary(con, rid, launcher=CF.fake_launcher(proc),
                           health_check=hc, switcher=sw, rollbacker=rb,
                           notifier=nt, good_commit="deadbeef")

        self.assertEqual(out["outcome"], "resolved")
        # 候选进程被起过又被收掉 (金丝雀一次性)。
        self.assertTrue(proc.started and proc.stopped)
        # 健康检查确实探的是候选进程而非主进程。
        self.assertEqual(hc.last_base_url, proc.base_url)
        # 冒烟过才切主进程, 切换带上 good_commit。
        self.assertEqual(sw.calls, 1)
        self.assertEqual(sw.commit, "deadbeef")
        # 成功不回滚。
        self.assertEqual(rb.calls, 0)
        # 状态机推进到 resolved, good_commit 记入。
        row = R.get(con, rid)
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["good_commit"], "deadbeef")
        self.assertIsNotNone(row["resolved_ts"])
        # 提交者收到通知。
        self.assertEqual(nt.calls, 1)
        self.assertIn("alice", nt.submitters)


# =============================================================================
# 健康/冒烟失败 -> 自动回滚 -> needs-human, switcher 绝不被调
# =============================================================================
class SmokeFailRollsBack(unittest.TestCase):
    def test_fail_rolls_back_to_good_commit_and_needs_human(self):
        con = store.connect(_tmpdb())
        rid = _patch_ready(con)
        proc = CF.FakeProcess()
        hc = CF.make_fake_health_check(ok=False, detail="/api/leaderboard 返回 500")
        sw = CF.make_fake_switcher()
        rb = CF.make_fake_rollbacker()
        nt = CF.make_fake_notifier()

        out = C.run_canary(con, rid, launcher=CF.fake_launcher(proc),
                           health_check=hc, switcher=sw, rollbacker=rb,
                           notifier=nt, good_commit="cafe1234")

        self.assertEqual(out["outcome"], "rolled-back")
        # 回滚到 good_commit。
        self.assertEqual(rb.calls, 1)
        self.assertEqual(rb.good_commit, "cafe1234")
        # 坏代码绝不接真实流量: switcher 一次都没被调, 也没通知提交者。
        self.assertEqual(sw.calls, 0)
        self.assertEqual(nt.calls, 0)
        # 候选进程仍被干净收掉。
        self.assertTrue(proc.stopped)
        # 转人工, 诊断含失败原因 + 回退锚点。
        row = R.get(con, rid)
        self.assertEqual(row["status"], "needs-human")
        self.assertIn("500", row["diagnosis"])
        self.assertIn("cafe1234", row["diagnosis"])


# =============================================================================
# in-flight -> 延迟到安静窗口; 强制才照跑
# =============================================================================
class DefersWhenBusy(unittest.TestCase):
    def _busy_con_with_patch(self):
        con = store.connect(_tmpdb())
        rid = _patch_ready(con)
        store.upsert_assignment(con, {"id": "a1", "task_id": "T1",
                                      "products": ["vio"], "status": "open"})
        store.claim_assignment(con, "a1", "runner1")   # -> claimed (busy)
        return con, rid

    def test_busy_defers_without_touching_process_or_state(self):
        con, rid = self._busy_con_with_patch()
        proc = CF.FakeProcess()
        sw = CF.make_fake_switcher()
        out = C.run_canary(con, rid, launcher=CF.fake_launcher(proc),
                           health_check=CF.make_fake_health_check(ok=True),
                           switcher=sw)
        self.assertEqual(out["outcome"], "deferred")
        self.assertEqual(out["inflight"]["claimed"], 1)
        # 候选进程都不起, 主进程不切, 状态仍停在 patch-ready。
        self.assertFalse(proc.started)
        self.assertEqual(sw.calls, 0)
        self.assertEqual(R.get(con, rid)["status"], "patch-ready")

    def test_allow_when_busy_forces_live(self):
        con, rid = self._busy_con_with_patch()
        proc = CF.FakeProcess()
        sw = CF.make_fake_switcher()
        out = C.run_canary(con, rid, launcher=CF.fake_launcher(proc),
                           health_check=CF.make_fake_health_check(ok=True),
                           switcher=sw, good_commit="g", allow_when_busy=True)
        self.assertEqual(out["outcome"], "resolved")
        self.assertTrue(proc.started)
        self.assertEqual(sw.calls, 1)
        self.assertEqual(R.get(con, rid)["status"], "resolved")


# =============================================================================
# reject: 转人工附留言; retry 再入队
# =============================================================================
class RejectPatch(unittest.TestCase):
    def test_reject_marks_needs_human_with_message(self):
        con = store.connect(_tmpdb())
        rid = _patch_ready(con)
        row = C.reject(con, rid, message="这个改动没解决问题, 颜色还是不对")
        self.assertEqual(row["status"], "needs-human")
        self.assertIn("颜色", row["diagnosis"])

    def test_reject_with_retry_requeues(self):
        con = store.connect(_tmpdb())
        rid = _patch_ready(con)
        row = C.reject(con, rid, message="再试一次, 用 flex 布局", retry=True)
        self.assertEqual(row["status"], "queued")

    def test_reject_only_on_patch_ready(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "alice", "x")            # submitted
        with self.assertRaises(C.CanaryError):
            C.reject(con, r["id"], message="no")


if __name__ == "__main__":
    unittest.main()
