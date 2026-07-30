"""#6: end-to-end proof that a spot-check ANOMALY actually revokes authorization.

The design (ADR-0011) says: spot-check finds a bad AI call -> fire the G2
recalibration trigger -> the reviewer/verifier subject is REVOKED and must clear
the golden set again. The wiring already exists in two places; this test proves
BOTH paths truly cut authorization end-to-end (not just record a note):

  Path A: sampling.submit_verdict(status="anomaly", role, name, members)
          — the reviewer files a verdict; anomaly fires check_authorization.
  Path B: review_queue.trigger_recalibration(owner) on an anomaly item
          — the owner-only 危险开关; RBAC rejects intern/reviewer.

Run: python -m unittest tests.test_anomaly_recalibration_e2e -v
"""
from __future__ import annotations
import unittest

from pipeline import authorize as AU
from pipeline import store
from pipeline import sampling
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


class PathA_SubmitVerdictAnomaly(unittest.TestCase):
    def setUp(self):
        self.con = _mem_db()
        self.members = ["review_deepseek", "review_gemini"]
        _authorize_reviewer(self.con, self.members)
        self.qid = _enqueue_one(self.con)

    def test_ok_verdict_does_not_revoke(self):
        out = sampling.submit_verdict(
            self.con, self.qid, status="ok", checked_by="rev1",
            role="reviewer", name="panel", members=self.members)
        self.assertFalse(out["recalibration_triggered"])
        self.assertEqual(
            store.get_authorization(self.con, "reviewer:panel")["status"],
            "authorized")

    def test_anomaly_verdict_revokes_authorization(self):
        out = sampling.submit_verdict(
            self.con, self.qid, status="anomaly", checked_by="rev1",
            verdict_note="AI graded high, human says fail",
            role="reviewer", name="panel", members=self.members)
        # the trigger fired and authorization is gone
        self.assertTrue(out["recalibration_triggered"])
        self.assertFalse(out["authorization"]["authorized"])
        self.assertEqual(out["authorization"]["status"], "revoked")
        self.assertIn("anomaly", out["authorization"]["reason"])
        # persisted revoke
        rec = store.get_authorization(self.con, "reviewer:panel")
        self.assertEqual(rec["status"], "revoked")
        # the human verdict is recorded on the queue item
        item = store.get_spot_check(self.con, self.qid)
        self.assertEqual(item["status"], "anomaly")

    def test_revoked_only_recovers_via_recalibration(self):
        sampling.submit_verdict(
            self.con, self.qid, status="anomaly", checked_by="rev1",
            role="reviewer", name="panel", members=self.members)
        # a plain check stays revoked
        r = AU.check_authorization(self.con, role="reviewer", name="panel",
                                   members=self.members)
        self.assertFalse(r["authorized"])
        # only recalibrating on the golden set restores it
        _authorize_reviewer(self.con, self.members)
        r2 = AU.check_authorization(self.con, role="reviewer", name="panel",
                                    members=self.members)
        self.assertTrue(r2["authorized"])


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
