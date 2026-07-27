"""MR-6 (#42): Assignment 状态机 + 并发领取.

验证外部行为, 不验实现细节:
  * 领取单元 = 整道对比任务 (含该域全部参赛产品, ADR-0015).
  * 并发领取: 两请求抢同一 Assignment, 仅一成功, 另一见已锁定.
  * 状态机 open/claimed/submitted/abandoned 合法流转, 非法跳转被拒.
  * 放弃或超时未交回到 open 可被再领.

Run: python -m unittest tests.test_assignment_state_machine_mr6 -v
"""
from __future__ import annotations
import tempfile
import pathlib
import unittest

from pipeline import store
from pipeline import assignments as A


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


def _seed_open(con, aid="a1", task="T1", products=("vio", "op", "sim")):
    store.upsert_assignment(con, {"id": aid, "task_id": task,
                                  "products": list(products)})


class Materialize(unittest.TestCase):
    """领取单元 = 整道对比任务, 含该域全部参赛产品 (ADR-0015)."""

    def test_materialize_pulls_participating_set(self):
        con = store.connect(_tmpdb())
        a = A.materialize_for_task(con, "T1-wechat-send-001")
        self.assertEqual(a["status"], "open")
        # 产品集 = catalog 参赛集 (GATE 派生, 含 vio + 够得着的竞品).
        self.assertIn("vio", a["products"])
        self.assertGreaterEqual(len(a["products"]), 2)  # 整组对打, 非单产品

    def test_materialize_missing_task_raises(self):
        con = store.connect(_tmpdb())
        with self.assertRaises(A.AssignmentError):
            A.materialize_for_task(con, "no-such-task")

    def test_materialize_idempotent_on_task(self):
        con = store.connect(_tmpdb())
        a1 = A.materialize_for_task(con, "T1-wechat-send-001")
        a2 = A.materialize_for_task(con, "T1-wechat-send-001")
        self.assertEqual(a1["id"], a2["id"])            # 复用原单, 不重复挂
        self.assertEqual(len(store.open_assignments(con)), 1)

    def test_materialize_does_not_reset_claimed(self):
        # 已被领的题再物化 (registry 刷新), status 不被重置回 open.
        con = store.connect(_tmpdb())
        a = A.materialize_for_task(con, "T1-wechat-send-001")
        A.claim(con, a["id"], "u1")
        again = A.materialize_for_task(con, "T1-wechat-send-001")
        self.assertEqual(again["status"], "claimed")
        self.assertEqual(again["claimed_by"], "u1")


class TransitionTable(unittest.TestCase):
    """合法流转表 —— 状态机单向, 非法跳转 fail closed."""

    def test_legal_transitions(self):
        self.assertTrue(A.can_transition("open", "claimed"))
        self.assertTrue(A.can_transition("claimed", "submitted"))
        self.assertTrue(A.can_transition("claimed", "abandoned"))

    def test_illegal_transitions_rejected(self):
        # 越级 / 倒流 / 终态再流转全非法.
        self.assertFalse(A.can_transition("open", "submitted"))
        self.assertFalse(A.can_transition("submitted", "claimed"))
        self.assertFalse(A.can_transition("submitted", "open"))
        self.assertFalse(A.can_transition("claimed", "open"))   # 回 open 只经 abandon
        self.assertFalse(A.can_transition("open", "abandoned"))

    def test_unknown_state_fails_closed(self):
        self.assertFalse(A.can_transition("bogus", "claimed"))
        self.assertFalse(A.can_transition("claimed", "bogus"))


class ClaimStateMachine(unittest.TestCase):
    def test_claim_open_succeeds(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        a = A.claim(con, "a1", "u1")
        self.assertEqual(a["status"], "claimed")
        self.assertEqual(a["claimed_by"], "u1")

    def test_claim_missing_raises(self):
        con = store.connect(_tmpdb())
        with self.assertRaises(A.AssignmentError):
            A.claim(con, "nope", "u1")

    def test_claim_already_claimed_is_illegal(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        A.claim(con, "a1", "u1")
        with self.assertRaises(A.IllegalTransition):
            A.claim(con, "a1", "u2")           # 第二人见已锁定
        a = store.get_assignment(con, "a1")
        self.assertEqual(a["claimed_by"], "u1")  # 第一人保住

    def test_concurrent_claim_single_winner(self):
        # 两条独立连接模拟并发, 只有一个 claim() 不抛异常.
        path = _tmpdb()
        con0 = store.connect(path)
        _seed_open(con0)
        conA, conB = store.connect(path), store.connect(path)
        outcomes = []
        for con, uid in ((conA, "uA"), (conB, "uB")):
            try:
                A.claim(con, "a1", uid)
                outcomes.append(True)
            except A.IllegalTransition:
                outcomes.append(False)
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(outcomes.count(False), 1)


class SubmitAbandon(unittest.TestCase):
    def test_submit_requires_claimed(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        with self.assertRaises(A.IllegalTransition):
            A.submit(con, "a1", by="u1")       # open 不能直接 submit
        A.claim(con, "a1", "u1")
        a = A.submit(con, "a1", by="u1")
        self.assertEqual(a["status"], "submitted")

    def test_submit_only_by_holder(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        A.claim(con, "a1", "u1")
        with self.assertRaises(A.AssignmentError):
            A.submit(con, "a1", by="u2")       # 非持有者不能交

    def test_submitted_is_terminal(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        A.claim(con, "a1", "u1")
        A.submit(con, "a1", by="u1")
        with self.assertRaises(A.IllegalTransition):
            A.abandon(con, "a1", by="u1")      # 交付后不能再放弃
        with self.assertRaises(A.IllegalTransition):
            A.submit(con, "a1", by="u1")       # 也不能重复交

    def test_abandon_reopens_and_reclaimable(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        A.claim(con, "a1", "u1")
        a = A.abandon(con, "a1", by="u1")
        self.assertEqual(a["status"], "open")
        self.assertIsNone(a["claimed_by"])
        b = A.claim(con, "a1", "u2")           # 别人可再领
        self.assertEqual(b["claimed_by"], "u2")

    def test_abandon_only_by_holder(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        A.claim(con, "a1", "u1")
        with self.assertRaises(A.AssignmentError):
            A.abandon(con, "a1", by="u2")

    def test_abandon_requires_claimed(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        with self.assertRaises(A.IllegalTransition):
            A.abandon(con, "a1", by="u1")      # open 无从放弃


class ReclaimStale(unittest.TestCase):
    def test_stale_claimed_reclaimed(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        A.claim(con, "a1", "u1")
        # claimed_ts 是刚才; 用一个远未来的 now 触发超时.
        import time
        reclaimed = A.reclaim_stale(con, ttl_seconds=1.0,
                                    now=time.time() + 10)
        self.assertEqual(reclaimed, ["a1"])
        a = store.get_assignment(con, "a1")
        self.assertEqual(a["status"], "open")
        self.assertIsNone(a["claimed_by"])

    def test_fresh_claim_not_reclaimed(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        A.claim(con, "a1", "u1")
        reclaimed = A.reclaim_stale(con, ttl_seconds=3600)
        self.assertEqual(reclaimed, [])
        self.assertEqual(store.get_assignment(con, "a1")["status"], "claimed")

    def test_submitted_not_reclaimed(self):
        con = store.connect(_tmpdb())
        _seed_open(con)
        A.claim(con, "a1", "u1")
        A.submit(con, "a1", by="u1")
        import time
        reclaimed = A.reclaim_stale(con, ttl_seconds=1.0, now=time.time() + 10)
        self.assertEqual(reclaimed, [])        # 已交付不算卡死


if __name__ == "__main__":
    unittest.main()
