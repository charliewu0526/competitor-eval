"""G2 (#25): golden-set authorization + Cohen's kappa + recalibration triggers.

Run: python -m unittest tests.test_authorize_g2 -v

Acceptance (issue #25), all OFFLINE:
  - reviewer/verifier run the golden set; Cohen's kappa is computed + RECORDED
  - v1 has NO hard-threshold gate — clearing the run authorizes regardless of kappa
  - the bias profile is RECORD-ONLY (never feeds back into a sample_score)
  - model-version / rubric / audit-anomaly trigger -> authorization AUTO-REVOKED
  - a revoked subject only recovers by recalibrating on the golden set
"""
from __future__ import annotations
import unittest

from pipeline import authorize as AU
from pipeline import store
from pipeline import golden
from pipeline import verify_fakes as VF


def _mem_db():
    return store.connect(":memory:")


# =============================================================================
# Cohen's kappa math.
# =============================================================================
class KappaMath(unittest.TestCase):
    def test_perfect_agreement(self):
        a = ["high", "fail", "partial", "high"]
        r = AU.cohens_kappa(a, a)
        self.assertEqual(r["agreement"], 1.0)
        self.assertEqual(r["kappa"], 1.0)

    def test_independent_disagreement_low_kappa(self):
        a = ["high", "high", "fail", "fail"]
        b = ["fail", "fail", "high", "high"]
        r = AU.cohens_kappa(a, b)
        self.assertEqual(r["agreement"], 0.0)
        self.assertLess(r["kappa"], 0)            # worse than chance

    def test_single_label_kappa_undefined_reports_agreement(self):
        # both raters use only "pass" -> pe==1 -> kappa undefined, agreement=1
        r = AU.cohens_kappa(["pass"] * 5, ["pass"] * 5)
        self.assertIsNone(r["kappa"])
        self.assertEqual(r["agreement"], 1.0)

    def test_empty(self):
        r = AU.cohens_kappa([], [])
        self.assertEqual(r["n"], 0)
        self.assertIsNone(r["kappa"])

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            AU.cohens_kappa(["a"], ["a", "b"])

    def test_confusion_matrix_counts(self):
        r = AU.cohens_kappa(["high", "fail"], ["high", "high"])
        self.assertEqual(r["confusion"]["high"]["high"], 1)
        self.assertEqual(r["confusion"]["fail"]["high"], 1)


# =============================================================================
# Label derivation off the golden set.
# =============================================================================
class Labels(unittest.TestCase):
    def test_score_buckets(self):
        self.assertEqual(AU.score_bucket(None), "unscored")
        self.assertEqual(AU.score_bucket(0.0), "fail")
        self.assertEqual(AU.score_bucket(0.5), "partial")
        self.assertEqual(AU.score_bucket(0.75), "high")
        self.assertEqual(AU.score_bucket(1.0), "high")

    def test_reviewer_labels_align_length(self):
        ai, human = AU.reviewer_labels()
        self.assertEqual(len(ai), len(golden.load_samples()))
        self.assertEqual(len(ai), len(human))

    def test_human_verdict_only_success_passes(self):
        for s in golden.load_samples():
            v = AU.human_verdict(s)
            self.assertEqual(v, "pass" if s["category"] == "success" else "fail")

    def test_verifier_labels_with_oracle_fn(self):
        # an ORACLE verifier (returns the human truth) -> perfect agreement
        oracle = lambda s: s["category"] == "success"
        ai, human = AU.verifier_labels(oracle)
        self.assertEqual(ai, human)


# =============================================================================
# Bias profile is record-only and reflects 宽严.
# =============================================================================
class BiasProfile(unittest.TestCase):
    def test_bias_keys_are_panelists(self):
        prof = AU.bias_profile()
        # golden panels use m0/m1/m2... names
        self.assertTrue(all(isinstance(k, str) for k in prof))
        self.assertTrue(prof, "bias profile should not be empty")

    def test_bias_does_not_touch_scores(self):
        # scoring a sample twice yields the SAME sample_score regardless of bias.
        s = golden.load_samples()[0]
        AU.bias_profile()  # compute (a no-op side-effect-wise)
        a = golden.score_sample(s)["sample_score"]
        b = golden.score_sample(s)["sample_score"]
        self.assertEqual(a, b)


# =============================================================================
# Fingerprints change when identity / rubric changes.
# =============================================================================
class Fingerprints(unittest.TestCase):
    def test_model_fingerprint_order_sensitive(self):
        self.assertNotEqual(AU.model_fingerprint(["a", "b"]),
                            AU.model_fingerprint(["b", "a"]))

    def test_model_fingerprint_version_sensitive(self):
        self.assertNotEqual(AU.model_fingerprint(["deepseek-v4"]),
                            AU.model_fingerprint(["deepseek-v5"]))

    def test_rubric_fingerprint_stable(self):
        self.assertEqual(AU.rubric_fingerprint(), AU.rubric_fingerprint())


# =============================================================================
# recalibrate(): runs golden, RECORDS kappa, authorizes WITHOUT a threshold.
# =============================================================================
class Recalibrate(unittest.TestCase):
    def test_reviewer_recalibrate_records_kappa_and_authorizes(self):
        con = _mem_db()
        rec = AU.recalibrate(con, role="reviewer", name="panel",
                             members=["deepseek-v4", "gemini-2"])
        self.assertEqual(rec["status"], "authorized")
        self.assertIn("kappa", rec)
        self.assertEqual(rec["n_samples"], len(golden.load_samples()))
        # persisted
        got = store.get_authorization(con, "reviewer:panel")
        self.assertEqual(got["status"], "authorized")
        self.assertEqual(got["n_samples"], rec["n_samples"])

    def test_graded_threshold_low_kappa_rejected(self):
        # ADR-0011 v2: kappa now GATES the status (lenient 0.4/0.2 tiers). A
        # DELIBERATELY bad verifier (always fail -> poor kappa) must NOT be
        # authorized — it is graded 'rejected' (退回人工). (v1 used to authorize
        # unconditionally; that漏洞 is now closed.)
        con = _mem_db()
        always_fail = lambda s: False
        rec = AU.recalibrate(con, role="verifier", name="claude",
                             members=["claude-opus-4"], verify_fn=always_fail)
        self.assertEqual(rec["status"], "rejected")
        # kappa + weighted kappa + CI are all recorded for observation
        self.assertIn("kappa", rec)
        self.assertIn("weighted_kappa", rec)
        self.assertIn("kappa_ci_low", rec)

    def test_grade_tiers_map_kappa_to_status(self):
        self.assertEqual(AU.grade_authorization(0.7), "authorized")
        self.assertEqual(AU.grade_authorization(0.4), "authorized")
        self.assertEqual(AU.grade_authorization(0.3), "observe")
        self.assertEqual(AU.grade_authorization(0.2), "observe")
        self.assertEqual(AU.grade_authorization(0.1), "rejected")
        self.assertEqual(AU.grade_authorization(None), "observe")

    def test_oracle_verifier_authorized(self):
        # a well-behaved (oracle) verifier clears the bar -> authorized.
        con = _mem_db()
        oracle = lambda s: s["category"] == "success"
        rec = AU.recalibrate(con, role="verifier", name="claude",
                             members=["claude-opus-4"], verify_fn=oracle)
        self.assertEqual(rec["status"], "authorized")

    def test_bias_profile_persisted_recorded_only(self):
        con = _mem_db()
        AU.recalibrate(con, role="reviewer", name="panel", members=["m"])
        got = store.get_authorization(con, "reviewer:panel")
        self.assertIsNotNone(got["bias_profile_json"])

    def test_verifier_requires_verify_fn(self):
        con = _mem_db()
        with self.assertRaises(ValueError):
            AU.recalibrate(con, role="verifier", name="x", members=["m"])


# =============================================================================
# check_authorization(): the gate + the three recalibration triggers.
# =============================================================================
class CheckAndTriggers(unittest.TestCase):
    def setUp(self):
        self.con = _mem_db()
        self.members = ["deepseek-v4", "gemini-2"]
        AU.recalibrate(self.con, role="reviewer", name="panel",
                       members=self.members)

    def test_uncalibrated_subject_not_authorized(self):
        r = AU.check_authorization(self.con, role="verifier", name="nobody",
                                   members=["m"])
        self.assertFalse(r["authorized"])
        self.assertEqual(r["status"], "uncalibrated")

    def test_authorized_when_nothing_changed(self):
        r = AU.check_authorization(self.con, role="reviewer", name="panel",
                                   members=self.members)
        self.assertTrue(r["authorized"])

    def test_model_version_change_revokes(self):
        r = AU.check_authorization(self.con, role="reviewer", name="panel",
                                   members=["deepseek-v5", "gemini-2"])  # bumped
        self.assertFalse(r["authorized"])
        self.assertEqual(r["status"], "revoked")
        self.assertIn("model", r["reason"])
        # revoke persisted -> stays revoked even if members revert
        again = AU.check_authorization(self.con, role="reviewer", name="panel",
                                       members=self.members)
        self.assertFalse(again["authorized"])

    def test_audit_anomaly_revokes(self):
        r = AU.check_authorization(self.con, role="reviewer", name="panel",
                                   members=self.members, anomaly=True)
        self.assertFalse(r["authorized"])
        self.assertEqual(r["status"], "revoked")
        self.assertIn("anomaly", r["reason"])

    def test_rubric_change_revokes(self):
        # monkeypatch the rubric fingerprint to simulate a rubric edit
        orig = AU.rubric_fingerprint
        AU.rubric_fingerprint = lambda: "DIFFERENT_RUBRIC_HASH"
        try:
            r = AU.check_authorization(self.con, role="reviewer", name="panel",
                                       members=self.members)
        finally:
            AU.rubric_fingerprint = orig
        self.assertFalse(r["authorized"])
        self.assertIn("rubric", r["reason"])

    def test_recovery_only_via_recalibration(self):
        # trigger a revoke...
        AU.check_authorization(self.con, role="reviewer", name="panel",
                               members=["deepseek-v5", "gemini-2"], )
        self.assertEqual(store.get_authorization(self.con, "reviewer:panel")["status"],
                         "revoked")
        # ...a plain check does NOT restore it...
        r = AU.check_authorization(self.con, role="reviewer", name="panel",
                                   members=self.members)
        self.assertFalse(r["authorized"])
        # ...only recalibrating on the golden set recovers authorization.
        AU.recalibrate(self.con, role="reviewer", name="panel",
                       members=self.members)
        r2 = AU.check_authorization(self.con, role="reviewer", name="panel",
                                    members=self.members)
        self.assertTrue(r2["authorized"])


if __name__ == "__main__":
    unittest.main()
