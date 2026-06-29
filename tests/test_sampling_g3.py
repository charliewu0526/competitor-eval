"""G3 (#26): layered human spot-check — 10% / 100% / 100%.

Run: python -m unittest tests.test_sampling_g3 -v

Acceptance (issue #26), all OFFLINE:
  - 抽查队列按规则采样：普通随机 10%、矛盾 100%、高风险 100%
  - 抽查为异步，主流程入库 (persist_eval) 不等待人工处理
  - 矛盾项（E3 标红）必然进入 100% 抽查队列
  - 抽查结果可回写并触发 G2 的「抽查异常 → 重校准」
  - 看板/队列能列出待抽查项及其分层原因
"""
from __future__ import annotations
import tempfile
import pathlib
import unittest

from pipeline import store, sampling as SP, authorize as AU, golden


def _tmpdb():
    d = tempfile.mkdtemp()
    return str(pathlib.Path(d) / "t.db")


def _score(task, product, *, run_idx=1, gate="native-operable", sample=0.8,
           h1=None, scored=True, disagreement=None):
    return {"task_id": task, "product": product, "run_idx": run_idx,
            "gate": gate, "scored": scored, "reason": None,
            "objective_ratio": 1.0, "sample_score": sample, "h1_honesty": h1,
            "subjective": {"S1": 4}, "disagreement_flagged": disagreement or [],
            "defects": []}


# =============================================================================
# Seeded 10% sampling — deterministic, ~rate proportion.
# =============================================================================
class NormalSampling(unittest.TestCase):
    def test_seeded_is_deterministic(self):
        a = SP.in_normal_sample("T1", "vio", 1)
        b = SP.in_normal_sample("T1", "vio", 1)
        self.assertEqual(a, b)

    def test_rate_is_roughly_ten_percent(self):
        hits = sum(SP.in_normal_sample("T%d" % i, "p", 1) for i in range(2000))
        # seeded hash → expect ~10%; allow generous band for n=2000.
        self.assertGreater(hits, 120)
        self.assertLess(hits, 280)

    def test_full_rate_selects_all(self):
        self.assertTrue(all(
            SP.in_normal_sample("T%d" % i, "p", 1, rate=1.0) for i in range(50)))


# =============================================================================
# Stratification rules + precedence.
# =============================================================================
class Classification(unittest.TestCase):
    def test_contradiction_always_100pct(self):
        sc = _score("T1", "rivalX", disagreement=["S2", "S3"])
        stratum, reason = SP.classify_run(sc, {})
        self.assertEqual(stratum, SP.CONTRADICTION)
        self.assertIn("S2", reason)

    def test_low_honesty_is_high_risk(self):
        sc = _score("T1", "rivalX", h1=2)
        stratum, reason = SP.classify_run(sc, {})
        self.assertEqual(stratum, SP.HIGH_RISK)
        self.assertIn("H1", reason)

    def test_honesty_alert_finding_is_high_risk(self):
        sc = _score("T1", "rivalX")
        findings = {("T1",): [{"task_id": "T1", "subject": "rivalX",
                               "suspected_category": "honesty-alert",
                               "routed_to": None}]}
        stratum, reason = SP.classify_run(sc, findings)
        self.assertEqual(stratum, SP.HIGH_RISK)
        self.assertIn("honesty-alert", reason)

    def test_routed_bug_is_high_risk(self):
        sc = _score("T1", "vio")
        findings = {("T1",): [{"task_id": "T1", "subject": "vio",
                               "suspected_category": "suspected-bug",
                               "routed_to": "bug-pipeline"}]}
        stratum, reason = SP.classify_run(sc, findings)
        self.assertEqual(stratum, SP.HIGH_RISK)
        self.assertIn("bug-pipeline", reason)

    def test_high_risk_beats_contradiction(self):
        # both flagged disagreement AND low honesty -> filed as high-risk.
        sc = _score("T1", "rivalX", h1=1, disagreement=["S2"])
        stratum, _ = SP.classify_run(sc, {})
        self.assertEqual(stratum, SP.HIGH_RISK)

    def test_normal_unsampled_returns_none(self):
        # find a key NOT in the 10% sample, with no risk/contradiction signal.
        for i in range(500):
            sc = _score("N%d" % i, "p")
            if not SP.in_normal_sample("N%d" % i, "p", 1):
                self.assertIsNone(SP.classify_run(sc, {}))
                return
        self.fail("expected at least one unsampled normal key")

    def test_finding_for_other_product_does_not_taint(self):
        sc = _score("T1", "vio")
        findings = {("T1",): [{"task_id": "T1", "subject": "rivalX",
                               "suspected_category": "honesty-alert",
                               "routed_to": None}]}
        # vio has no own high-risk signal; honesty-alert is about rivalX.
        decision = SP.classify_run(sc, findings)
        if decision is not None:
            self.assertNotEqual(decision[0], SP.HIGH_RISK)


# =============================================================================
# Queue building over the store.
# =============================================================================
class QueueBuild(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(_tmpdb())

    def test_build_enqueues_with_strata_and_reasons(self):
        store.upsert_score(self.con, _score("T1", "rivalX", disagreement=["S2"]))
        store.upsert_score(self.con, _score("T2", "rivalX", h1=1))
        summary = SP.build_queue(self.con)
        self.assertEqual(summary["by_stratum"]["contradiction"], 1)
        self.assertEqual(summary["by_stratum"]["high-risk"], 1)
        items = store.spot_check_queue(self.con)
        # every item carries a non-empty分层原因
        self.assertTrue(all(it["reason"] for it in items))
        # high-risk sorts before contradiction in the queue listing
        self.assertEqual(items[0]["stratum"], "high-risk")

    def test_cannot_reach_unscored_excluded(self):
        sc = _score("T3", "rivalY", gate="cannot-reach", scored=False,
                    disagreement=["S2"])
        store.upsert_score(self.con, sc)
        summary = SP.build_queue(self.con)
        self.assertEqual(summary["enqueued"], 0)

    def test_rebuild_is_idempotent_and_preserves_verdict(self):
        store.upsert_score(self.con, _score("T1", "rivalX", disagreement=["S2"]))
        SP.build_queue(self.con)
        qid = store.spot_check_queue(self.con)[0]["id"]
        SP.submit_verdict(self.con, qid, status="ok", checked_by="PM")
        # rebuild should NOT clobber the human verdict back to pending
        SP.build_queue(self.con)
        # it's no longer pending, so it drops out of the pending listing
        self.assertEqual(store.spot_check_queue(self.con, status="pending"), [])
        done = [r for r in store.spot_check_queue(self.con, status="ok")
                if r["id"] == qid]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["checked_by"], "PM")


# =============================================================================
# Async: persist_eval (main ingest) never touches the queue.
# =============================================================================
class AsyncDecoupling(unittest.TestCase):
    def test_persist_eval_does_not_enqueue(self):
        con = store.connect(_tmpdb())
        from pipeline.schema import RunRecord
        rr = RunRecord(task_id="T1", product="vio", run_idx=1,
                       gate="native-operable")
        sc = _score("T1", "vio", disagreement=["S2"])  # would be 100% if scanned
        store.persist_eval(con, [rr], [sc], [])
        # main path ingested, but queue is still empty — sampling is async.
        self.assertEqual(store.spot_check_queue(con), [])


# =============================================================================
# Verdict write-back -> G2 recalibration trigger.
# =============================================================================
class VerdictRecalibration(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(_tmpdb())
        store.upsert_score(self.con, _score("T1", "rivalX", disagreement=["S2"]))
        SP.build_queue(self.con)
        self.qid = store.spot_check_queue(self.con)[0]["id"]

    def test_ok_verdict_no_recalibration(self):
        out = SP.submit_verdict(self.con, self.qid, status="ok", checked_by="PM")
        self.assertTrue(out["recorded"])
        self.assertFalse(out["recalibration_triggered"])

    def test_anomaly_revokes_authorized_subject(self):
        # authorize a reviewer first, then an anomaly spot-check must revoke it.
        members = ["deepseek", "gemini"]
        AU.recalibrate(self.con, role="reviewer", name="panel", members=members,
                       samples=golden.load_samples())
        before = store.get_authorization(self.con, "reviewer:panel")
        self.assertEqual(before["status"], "authorized")
        out = SP.submit_verdict(self.con, self.qid, status="anomaly",
                                checked_by="PM", role="reviewer", name="panel",
                                members=members)
        self.assertTrue(out["recalibration_triggered"])
        after = store.get_authorization(self.con, "reviewer:panel")
        self.assertEqual(after["status"], "revoked")
        self.assertIn("anomaly", after["revoked_reason"])

    def test_bad_status_rejected(self):
        with self.assertRaises(ValueError):
            SP.submit_verdict(self.con, self.qid, status="maybe")


if __name__ == "__main__":
    unittest.main()
