"""MR-13 (#49): 人工复核队列 + 职责分离 + 重校准.

Run: python -m unittest tests.test_review_queue_mr13 -v

Acceptance (issue #49), all OFFLINE (real temp SQLite):
  - 大差距 / 分歧 / 谎报强制入复核队列, 其余抽查
  - 执行者不被指派复核自己执行的 Assignment (职责分离)
  - reviewer/PM 能对复核项下「有道理」/「有问题」结论
  - 「有问题」可触发重校准, 且仅 owner 能触发
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import (store, sampling as SP, review_queue as RQ,
                      rbac as RBAC, authorize as AU, golden)


def _tmpdb():
    d = tempfile.mkdtemp()
    return store.connect(str(pathlib.Path(d) / "t.db"))


def _score(task, product, *, run_idx=1, gate="native-operable", sample=0.8,
           h1=None, scored=True, disagreement=None):
    return {"task_id": task, "product": product, "run_idx": run_idx,
            "gate": gate, "scored": scored, "reason": None,
            "objective_ratio": 1.0, "sample_score": sample, "h1_honesty": h1,
            "subjective": {"S1": 4}, "disagreement_flagged": disagreement or [],
            "defects": []}


def _feature_gap_finding(task, product):
    """A machine feature-gap finding for (task, product) — the big-gap signal."""
    return {"task_id": task, "subject": product,
            "suspected_category": "feature-gap", "routed_to": None,
            "phenomenon": f"{product} 完成该任务而基线失败", "rule": "feature-gap"}


def _user(con, uid, role):
    store.upsert_user(con, {"id": uid, "name": uid, "role": role})
    return store.get_user(con, uid)


# =============================================================================
# 1. 大差距强制入队列 (复用 findings feature-gap, 同源).
# =============================================================================
class BigGapStratum(unittest.TestCase):
    def test_feature_gap_is_big_gap_stratum(self):
        sc = _score("T1", "rivalX")
        findings = {("T1",): [_feature_gap_finding("T1", "rivalX")]}
        stratum, reason = SP.classify_run(sc, findings)
        self.assertEqual(stratum, SP.BIG_GAP)
        self.assertIn("大差距", reason)

    def test_big_gap_is_100pct_regardless_of_sample(self):
        # even a key NOT in the 10% sample must be forced in by big-gap.
        findings = {("N%d" % 0,): [_feature_gap_finding("N0", "p")]}
        # find an unsampled normal key first
        for i in range(500):
            if not SP.in_normal_sample("N%d" % i, "p", 1):
                sc = _score("N%d" % i, "p")
                fnd = {("N%d" % i,): [_feature_gap_finding("N%d" % i, "p")]}
                stratum, _ = SP.classify_run(sc, fnd)
                self.assertEqual(stratum, SP.BIG_GAP)
                return
        self.fail("expected at least one unsampled normal key")

    def test_high_risk_beats_big_gap(self):
        # both low honesty AND a feature-gap finding -> filed high-risk.
        sc = _score("T1", "rivalX", h1=1)
        findings = {("T1",): [_feature_gap_finding("T1", "rivalX"),
                              {"task_id": "T1", "subject": "rivalX",
                               "suspected_category": "honesty-alert",
                               "routed_to": None}]}
        stratum, _ = SP.classify_run(sc, findings)
        self.assertEqual(stratum, SP.HIGH_RISK)

    def test_contradiction_beats_big_gap(self):
        sc = _score("T1", "rivalX", disagreement=["S2"])
        findings = {("T1",): [_feature_gap_finding("T1", "rivalX")]}
        stratum, _ = SP.classify_run(sc, findings)
        self.assertEqual(stratum, SP.CONTRADICTION)

    def test_build_queue_counts_big_gap(self):
        con = _tmpdb()
        store.upsert_score(con, _score("T1", "rivalX"))
        store.upsert_finding(con, _find_row("T1", "rivalX"))
        summary = SP.build_queue(con)
        self.assertEqual(summary["by_stratum"][SP.BIG_GAP], 1)
        items = store.spot_check_queue(con)
        self.assertEqual(items[0]["stratum"], SP.BIG_GAP)


def _find_row(task, product):
    """A store-shaped finding row (feature-gap) for build_queue integration."""
    return {"task_id": task, "rule": "feature-gap",
            "suspected_category": "feature-gap", "subject": product,
            "phenomenon": f"{product} 完成而基线失败",
            "evidence": [{"source": "artifact", "ref": "shot.png"}]}


# =============================================================================
# 2. 职责分离: 执行者不被指派复核同一条.
# =============================================================================
class SeparationOfDuties(unittest.TestCase):
    def setUp(self):
        self.con = _tmpdb()
        # an executor submitted (T1, rivalX); build a queue item for it.
        store.upsert_assignment(self.con, {
            "id": "ASG1", "task_id": "T1", "products": ["vio", "rivalX"],
            "status": "submitted", "claimed_by": "u-intern-1",
            "claimed_ts": 1.0, "created_ts": 1.0})
        store.upsert_submission(self.con, {
            "id": "sub1", "assignment_id": "ASG1", "product": "rivalX",
            "artifact_path": "/u/a.png", "log_bundle_path": "/u/l.json",
            "manual_assertions": {}, "machine_ctx": {},
            "claimed_success": True, "submitted_by": "u-intern-1",
            "submitted_ts": 2.0})
        store.upsert_score(self.con, _score("T1", "rivalX", disagreement=["S2"]))
        SP.build_queue(self.con)
        self.qid = store.spot_check_queue(self.con)[0]["id"]
        self.reviewer = _user(self.con, "u-reviewer-1", "reviewer")
        _user(self.con, "u-intern-1", "intern")

    def test_executor_lookup(self):
        ex = store.executors_for_task_product(self.con, "T1", "rivalX")
        self.assertEqual(ex, ["u-intern-1"])

    def test_executor_cannot_be_assigned(self):
        # u-intern-1 executed it -> ineligible as reviewer of the same run.
        self.assertFalse(RQ.eligible_reviewer(self.con, self.qid, "u-intern-1"))
        with self.assertRaises(RQ.SeparationOfDuties):
            RQ.assign_reviewer(self.con, self.qid, reviewer=self.reviewer,
                               reviewer_id="u-intern-1")

    def test_non_executor_can_be_assigned(self):
        self.assertTrue(RQ.eligible_reviewer(self.con, self.qid, "u-reviewer-1"))
        item = RQ.assign_reviewer(self.con, self.qid, reviewer=self.reviewer,
                                  reviewer_id="u-reviewer-1")
        self.assertEqual(item["assigned_reviewer"], "u-reviewer-1")

    def test_intern_cannot_assign(self):
        intern = store.get_user(self.con, "u-intern-1")
        with self.assertRaises(RBAC.PermissionDenied):
            RQ.assign_reviewer(self.con, self.qid, reviewer=intern,
                               reviewer_id="u-reviewer-1")


# =============================================================================
# 3. 复核结论 (有道理/有问题) + intern 不能复核.
# =============================================================================
class ReviewVerdict(unittest.TestCase):
    def setUp(self):
        self.con = _tmpdb()
        store.upsert_score(self.con, _score("T1", "rivalX", disagreement=["S2"]))
        SP.build_queue(self.con)
        self.qid = store.spot_check_queue(self.con)[0]["id"]
        self.reviewer = _user(self.con, "rev", "reviewer")
        self.owner = _user(self.con, "pm", "owner")
        self.intern = _user(self.con, "int", "intern")

    def test_reasonable_maps_to_ok(self):
        item = RQ.submit_verdict(self.con, self.qid, reviewer=self.reviewer,
                                 verdict=RQ.VERDICT_OK, note="看着没问题")
        self.assertEqual(item["status"], "ok")
        self.assertEqual(item["checked_by"], "rev")

    def test_problematic_maps_to_anomaly(self):
        item = RQ.submit_verdict(self.con, self.qid, reviewer=self.reviewer,
                                 verdict=RQ.VERDICT_PROBLEM)
        self.assertEqual(item["status"], "anomaly")

    def test_intern_cannot_review(self):
        with self.assertRaises(RBAC.PermissionDenied):
            RQ.submit_verdict(self.con, self.qid, reviewer=self.intern,
                              verdict=RQ.VERDICT_OK)

    def test_illegal_verdict_rejected(self):
        with self.assertRaises(RQ.ReviewError):
            RQ.submit_verdict(self.con, self.qid, reviewer=self.reviewer,
                              verdict="maybe")

    def test_assigned_reviewer_binds_who_can_conclude(self):
        RQ.assign_reviewer(self.con, self.qid, reviewer=self.owner,
                           reviewer_id="rev")
        other = _user(self.con, "rev2", "reviewer")
        with self.assertRaises(RQ.SeparationOfDuties):
            RQ.submit_verdict(self.con, self.qid, reviewer=other,
                              verdict=RQ.VERDICT_OK)
        # owner override still allowed
        item = RQ.submit_verdict(self.con, self.qid, reviewer=self.owner,
                                 verdict=RQ.VERDICT_OK)
        self.assertEqual(item["status"], "ok")


# =============================================================================
# 4. 重校准: 仅 owner, 且须先有「有问题」结论.
# =============================================================================
class RecalibrationOwnerOnly(unittest.TestCase):
    def setUp(self):
        self.con = _tmpdb()
        store.upsert_score(self.con, _score("T1", "rivalX", disagreement=["S2"]))
        SP.build_queue(self.con)
        self.qid = store.spot_check_queue(self.con)[0]["id"]
        self.reviewer = _user(self.con, "rev", "reviewer")
        self.owner = _user(self.con, "pm", "owner")
        self.members = ["deepseek", "gemini"]
        AU.recalibrate(self.con, role="reviewer", name="panel",
                       members=self.members, samples=golden.load_samples())

    def test_reviewer_cannot_recalibrate(self):
        RQ.submit_verdict(self.con, self.qid, reviewer=self.reviewer,
                          verdict=RQ.VERDICT_PROBLEM)
        with self.assertRaises(RBAC.PermissionDenied):
            RQ.trigger_recalibration(self.con, self.qid, actor=self.reviewer,
                                     members=self.members)

    def test_recalibration_requires_anomaly_verdict(self):
        # no「有问题」结论yet -> refuse (pending is not a trigger basis)
        with self.assertRaises(RQ.ReviewError):
            RQ.trigger_recalibration(self.con, self.qid, actor=self.owner,
                                     members=self.members)

    def test_owner_recalibration_revokes_authorization(self):
        RQ.submit_verdict(self.con, self.qid, reviewer=self.reviewer,
                          verdict=RQ.VERDICT_PROBLEM)
        before = store.get_authorization(self.con, "reviewer:panel")
        self.assertEqual(before["status"], "authorized")
        out = RQ.trigger_recalibration(self.con, self.qid, actor=self.owner,
                                       members=self.members)
        self.assertTrue(out["recalibration_triggered"])
        after = store.get_authorization(self.con, "reviewer:panel")
        self.assertEqual(after["status"], "revoked")
        # provenance stamped on the queue item (audit trail)
        item = store.get_spot_check(self.con, self.qid)
        self.assertEqual(item["recalibrated_by"], "pm")
        self.assertIsNotNone(item["recalibrated_ts"])


if __name__ == "__main__":
    unittest.main()
