"""MR-A (#55): User Report 状态机厚地基.

验证外部行为, 不验实现细节 (prior art: test_assignment_state_machine_mr6):
  * 建表在 SQLite 后端真实穿通 (PG 穿通见 test_postgres_passthrough_mr1b 的 MR-A 段).
  * 厚表一次性含齐 core + branch_name/diagnosis/diff_ref/test_result/good_commit/
    resolved_ts, 后续票无需再 migrate.
  * 全部合法状态转移可执行; 每一条非法转移被显式拒绝 (报错, 不静默).
  * User Report 与 Finding 两条流独立 (互不引用, ADR-0020).

Run: python -m unittest tests.test_reports_mra -v
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import store
from pipeline import reports as R


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


# 一次走完 happy path 到某个目标态的小工具 (少写样板).
def _advance(con, rid, path):
    for dst in path:
        R.transition(con, rid, dst)


class SchemaThickAndPassthrough(unittest.TestCase):
    """建表穿通 + 厚字段一次性到位 (AC1/AC2)."""

    def test_table_created_empty(self):
        con = store.connect(_tmpdb())
        n = con.execute("SELECT count(*) AS c FROM user_report").fetchone()["c"]
        self.assertEqual(n, 0)

    def test_all_thick_columns_present(self):
        con = store.connect(_tmpdb())
        cols = {row["name"] for row in
                con.execute("PRAGMA table_info(user_report)")}
        expected = {"id", "submitter", "status", "text", "created_ts",
                    "updated_ts", "branch_name", "diagnosis", "diff_ref",
                    "test_result", "good_commit", "resolved_ts"}
        self.assertTrue(expected.issubset(cols),
                        f"缺列: {expected - cols}")

    def test_create_persists_and_roundtrips(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "看板页白屏了")
        self.assertEqual(r["status"], "submitted")
        self.assertEqual(r["submitter"], "u1")
        self.assertEqual(r["text"], "看板页白屏了")
        # 重新读一遍, 落地无误.
        again = store.get_user_report(con, r["id"])
        self.assertEqual(again["text"], "看板页白屏了")

    def test_later_ticket_fields_writable_without_migration(self):
        # C/C2/D 的列此刻就能写, 无需再 migrate.
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        R.enqueue(con, r["id"])
        row = R.start_ai(con, r["id"], branch_name="fix/ur-123")
        self.assertEqual(row["branch_name"], "fix/ur-123")
        row = R.mark_patch_ready(con, r["id"], diff_ref="/srv/ur/123.diff",
                                 test_result="3 passed")
        self.assertEqual(row["diff_ref"], "/srv/ur/123.diff")
        self.assertEqual(row["test_result"], "3 passed")
        row = R.resolve(con, r["id"], good_commit="abc123")
        self.assertEqual(row["good_commit"], "abc123")
        self.assertIsNotNone(row["resolved_ts"])


class CreateGuards(unittest.TestCase):
    def test_submitter_required(self):
        con = store.connect(_tmpdb())
        with self.assertRaises(R.ReportError):
            R.create(con, "", "无主反馈")

    def test_duplicate_id_rejected(self):
        con = store.connect(_tmpdb())
        R.create(con, "u1", "x", report_id="ur-dup")
        with self.assertRaises(R.ReportError):
            R.create(con, "u1", "y", report_id="ur-dup")

    def test_get_missing_raises(self):
        con = store.connect(_tmpdb())
        with self.assertRaises(R.ReportError):
            R.get(con, "no-such")


class TransitionTable(unittest.TestCase):
    """合法流转表 —— 单向, 非法跳转 fail closed (纯表, 不碰 DB)."""

    def test_legal_transitions(self):
        self.assertTrue(R.can_transition("submitted", "queued"))
        self.assertTrue(R.can_transition("queued", "ai-working"))
        # 三分叉.
        self.assertTrue(R.can_transition("ai-working", "patch-ready"))
        self.assertTrue(R.can_transition("ai-working", "needs-human"))
        self.assertTrue(R.can_transition("ai-working", "ai-failed"))
        # owner 审.
        self.assertTrue(R.can_transition("patch-ready", "resolved"))
        self.assertTrue(R.can_transition("patch-ready", "needs-human"))
        # 重试回路 + 收口.
        self.assertTrue(R.can_transition("needs-human", "queued"))
        self.assertTrue(R.can_transition("ai-failed", "queued"))
        self.assertTrue(R.can_transition("needs-human", "closed"))
        self.assertTrue(R.can_transition("ai-failed", "closed"))
        self.assertTrue(R.can_transition("resolved", "closed"))

    def test_illegal_transitions_rejected(self):
        # 越级.
        self.assertFalse(R.can_transition("submitted", "ai-working"))
        self.assertFalse(R.can_transition("submitted", "resolved"))
        self.assertFalse(R.can_transition("queued", "patch-ready"))
        # 倒流.
        self.assertFalse(R.can_transition("ai-working", "queued"))
        self.assertFalse(R.can_transition("patch-ready", "ai-working"))
        self.assertFalse(R.can_transition("resolved", "patch-ready"))
        # patch-ready 不能直接 closed (必须先 resolved 或退 needs-human).
        self.assertFalse(R.can_transition("patch-ready", "closed"))
        # queued 不能直接分叉 (必须先经 ai-working).
        self.assertFalse(R.can_transition("queued", "needs-human"))

    def test_terminal_closed_has_no_exit(self):
        for dst in R.STATES:
            self.assertFalse(R.can_transition("closed", dst), dst)

    def test_unknown_state_fails_closed(self):
        self.assertFalse(R.can_transition("bogus", "queued"))
        self.assertFalse(R.can_transition("queued", "bogus"))


class DrivenTransitions(unittest.TestCase):
    """真驱一条 report 走完各条合法路径, 非法调用抛错."""

    def test_happy_path_to_resolved_closed(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        R.enqueue(con, r["id"])
        self.assertEqual(store.get_user_report(con, r["id"])["status"], "queued")
        R.start_ai(con, r["id"])
        self.assertEqual(store.get_user_report(con, r["id"])["status"], "ai-working")
        R.mark_patch_ready(con, r["id"])
        R.resolve(con, r["id"])
        R.close(con, r["id"])
        self.assertEqual(store.get_user_report(con, r["id"])["status"], "closed")

    def test_three_way_needs_human_and_retry(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        _advance(con, r["id"], ["queued", "ai-working"])
        R.mark_needs_human(con, r["id"], diagnosis="碰了鉴权禁区")
        row = store.get_user_report(con, r["id"])
        self.assertEqual(row["status"], "needs-human")
        self.assertEqual(row["diagnosis"], "碰了鉴权禁区")
        # owner 让 AI 重试 -> 回 queued.
        R.enqueue(con, r["id"])
        self.assertEqual(store.get_user_report(con, r["id"])["status"], "queued")

    def test_three_way_ai_failed_then_close(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        _advance(con, r["id"], ["queued", "ai-working"])
        R.mark_ai_failed(con, r["id"], diagnosis="测试没过")
        self.assertEqual(store.get_user_report(con, r["id"])["status"], "ai-failed")
        R.close(con, r["id"])
        self.assertEqual(store.get_user_report(con, r["id"])["status"], "closed")

    def test_owner_reject_patch_back_to_needs_human(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        _advance(con, r["id"], ["queued", "ai-working", "patch-ready"])
        R.mark_needs_human(con, r["id"], diagnosis="diff 不对")
        self.assertEqual(store.get_user_report(con, r["id"])["status"], "needs-human")

    def test_illegal_driven_transition_raises(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        # submitted 不能直接 resolve.
        with self.assertRaises(R.IllegalTransition):
            R.resolve(con, r["id"])
        # submitted 不能直接分叉.
        with self.assertRaises(R.IllegalTransition):
            R.mark_patch_ready(con, r["id"])

    def test_terminal_closed_cannot_transition(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        _advance(con, r["id"], ["queued", "ai-working", "ai-failed", "closed"])
        with self.assertRaises(R.IllegalTransition):
            R.enqueue(con, r["id"])

    def test_illegal_field_rejected(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        with self.assertRaises(ValueError):
            R.transition(con, r["id"], "queued", fields={"bogus": 1})

    def test_store_guard_blocks_stale_transition(self):
        # 带 expected_from 守卫: 状态已被并发推进后, 旧的 src 流转命中 0 行 -> 抛错.
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "x")
        # 直接用 store 把它推到 queued (模拟并发方先动了).
        store.set_user_report_status(con, r["id"], "queued")
        # 现在按 submitted->queued 再走一次策略层, src 读到 queued, 试图 queued->queued
        # 是非法转移, 先被 _require_transition 拦 (证明守卫链生效).
        with self.assertRaises(R.IllegalTransition):
            R.enqueue(con, r["id"])


class QueriesAndStreams(unittest.TestCase):
    def test_reports_by_status_and_submitter(self):
        con = store.connect(_tmpdb())
        a = R.create(con, "u1", "a")
        b = R.create(con, "u2", "b")
        R.enqueue(con, a["id"])
        self.assertEqual([x["id"] for x in store.reports_by_status(con, "queued")],
                         [a["id"]])
        self.assertEqual([x["id"] for x in store.reports_by_status(con, "submitted")],
                         [b["id"]])
        self.assertEqual([x["id"] for x in store.reports_for_submitter(con, "u1")],
                         [a["id"]])
        self.assertEqual(len(store.all_user_reports(con)), 2)

    def test_report_and_finding_are_separate_streams(self):
        """ADR-0020: 两张独立表, 互不引用. user_report 无 finding 外键, 反之亦然."""
        con = store.connect(_tmpdb())
        ur_cols = {row["name"] for row in
                   con.execute("PRAGMA table_info(user_report)")}
        fnd_cols = {row["name"] for row in
                    con.execute("PRAGMA table_info(findings)")}
        # user_report 不含任何 finding 引用列, findings 不含任何 report 引用列.
        self.assertFalse(any("finding" in c for c in ur_cols), ur_cols)
        self.assertFalse(any("report" in c for c in fnd_cols), fnd_cols)
        # 两表都真实存在且独立可查.
        R.create(con, "u1", "x")
        self.assertEqual(len(store.all_user_reports(con)), 1)
        self.assertEqual(
            con.execute("SELECT count(*) AS c FROM findings").fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
