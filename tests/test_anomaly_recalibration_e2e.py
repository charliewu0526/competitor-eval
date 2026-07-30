"""#6: end-to-end proof that a spot-check ANOMALY actually revokes authorization.

The design (ADR-0011) says: spot-check finds a bad AI call -> fire the G2
recalibration trigger -> the reviewer/verifier subject is REVOKED and must clear
the golden set again.

裁决收敛 (抽查体验重构): 旧的 Path A (sampling.submit_verdict status="anomaly")
简单裁决那套已删除, 撤授权统一由 owner 独占的 review_queue.trigger_recalibration
承担 (Path B)。本文件只保留 Path B 的端到端证明:

  Path B: review_queue.trigger_recalibration(owner) on an anomaly item
          — the owner-only 危险开关; RBAC rejects intern/reviewer; 真撤授权。

Run: python -m unittest tests.test_anomaly_recalibration_e2e -v
"""
from __future__ import annotations
import unittest

from pipeline import authorize as AU
from pipeline import store
from pipeline import review_queue as RQ
from pipeline.rbac import PermissionDenied


def _mem_db():
    return store.connect(":memory:")


def _authorize_reviewer(con, members):
    """Recalibrate reviewer:panel to an authorized baseline (oracle-ish)."""
    return AU.recalibrate(con, role="reviewer", name="panel", members=members)


def _enqueue_one(con):
    return store.enqueue_spot_check(
        con, task_id="T1", product="vio", run_idx=1,
        stratum="high-risk", reason="honesty flag")


class PathB_TriggerRecalibrationOwnerOnly(unittest.TestCase):
    def setUp(self):
        self.con = _mem_db()
        self.members = ["review_deepseek", "review_gemini"]
        _authorize_reviewer(self.con, self.members)
        self.qid = _enqueue_one(self.con)
        # an anomaly verdict must exist before recalibration can be triggered
        store.record_spot_check(self.con, self.qid, status="anomaly",
                                checked_by="rev1",
                                verdict_note="human disagrees")
        self.owner = {"id": "u_owner", "name": "PM", "role": "owner"}
        self.intern = {"id": "u_intern", "name": "Intern", "role": "intern"}
        self.reviewer = {"id": "u_rev", "name": "Rev", "role": "reviewer"}

    def test_owner_trigger_revokes_and_stamps_provenance(self):
        out = RQ.trigger_recalibration(
            self.con, self.qid, actor=self.owner,
            role="reviewer", name="panel", members=self.members)
        self.assertTrue(out["recalibration_triggered"])
        self.assertFalse(out["authorization"]["authorized"])
        self.assertEqual(out["authorization"]["status"], "revoked")
        # authorization actually revoked in the store
        self.assertEqual(
            store.get_authorization(self.con, "reviewer:panel")["status"],
            "revoked")
        # provenance stamped on the queue item
        item = out["item"]
        self.assertEqual(item["recalibrated_by"], "u_owner")
        self.assertIsNotNone(item["recalibrated_ts"])

    def test_intern_and_reviewer_cannot_trigger(self):
        for actor in (self.intern, self.reviewer, None):
            with self.assertRaises(PermissionDenied):
                RQ.trigger_recalibration(
                    self.con, self.qid, actor=actor,
                    role="reviewer", name="panel", members=self.members)
        # authorization untouched by the rejected attempts
        self.assertEqual(
            store.get_authorization(self.con, "reviewer:panel")["status"],
            "authorized")

    def test_cannot_trigger_without_anomaly_verdict(self):
        # a fresh pending item (no anomaly) must be refused
        qid2 = store.enqueue_spot_check(
            self.con, task_id="T2", product="vio", run_idx=1,
            stratum="normal", reason="random sample")
        with self.assertRaises(RQ.ReviewError):
            RQ.trigger_recalibration(
                self.con, qid2, actor=self.owner,
                role="reviewer", name="panel", members=self.members)


if __name__ == "__main__":
    unittest.main()
