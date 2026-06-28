"""E5: findings pre-classification — eval products -> 「发现 Finding」.

Run: python -m unittest tests.test_findings_e5 -v

Acceptance (issue #E5):
  - 竞品完成 + Vio 失败 -> 疑似 feature-gap
  - 发现无证据 -> 不入池
  - 机器只写「疑似」+ 现象，product_judgment/final_category 留空待 PM 填
  - Vio 末态失败 -> 自动进 bug pipeline，含 repro(task/env/steps/evidence)
  - 5 条规则各有一条合成用例覆盖

Seam-internal, deterministic, offline. We feed synthetic score dicts (the shape
score_run() emits) and assert the Findings.
"""
from __future__ import annotations
import unittest
from pipeline import findings as F


def _score(product, *, sample=None, failed_primary=False, h1=None,
           s5=None, reason=None):
    out = {"product": product, "objective_failed_primary": failed_primary}
    if sample is not None:
        out["sample_score"] = sample
    if h1 is not None:
        out["h1_honesty"] = h1
    if s5 is not None:
        out["subjective"] = {"S1": 4, "S2": 4, "S3": 4, "S4": 4, "S5": s5}
    if reason:
        out["reason"] = reason
    return out


EV = lambda src="log", ref="run.json": {"source": src, "ref": ref}


class FeatureGapRule(unittest.TestCase):
    def test_competitor_passes_vio_fails(self):
        scores = [
            _score("vio", failed_primary=True, sample=0.0, reason="primary failed"),
            _score("simular", sample=0.8),
        ]
        ev = {"simular": [EV()], "vio": [EV()]}
        fs = F.classify("T1", scores, ev)
        gaps = [f for f in fs if f.suspected_category == "feature-gap"
                and f.subject == "simular"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].rule, "feature-gap")

    def test_no_evidence_not_emitted(self):
        scores = [
            _score("vio", failed_primary=True, sample=0.0),
            _score("simular", sample=0.8),
        ]
        # competitor has NO evidence -> 无证据不入池
        ev = {"vio": [EV()]}
        fs = F.classify("T1", scores, ev)
        gaps = [f for f in fs if f.subject == "simular"]
        self.assertEqual(gaps, [])


class CapabilityLeadRule(unittest.TestCase):
    def test_both_pass_competitor_leads(self):
        scores = [_score("vio", sample=0.5), _score("simular", sample=0.8)]
        ev = {"simular": [EV()]}
        fs = F.classify("T1", scores, ev)
        leads = [f for f in fs if f.rule == "capability-lead"]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].suspected_category, "feature-gap")

    def test_lead_below_threshold_no_finding(self):
        scores = [_score("vio", sample=0.7), _score("simular", sample=0.75)]
        ev = {"simular": [EV()]}
        fs = F.classify("T1", scores, ev)
        self.assertEqual([f for f in fs if f.rule == "capability-lead"], [])


class ExperienceBorrowRule(unittest.TestCase):
    def test_competitor_s5_leads(self):
        scores = [_score("vio", sample=0.6, s5=3),
                  _score("simular", sample=0.6, s5=5)]
        ev = {"simular": [EV("screenshot")]}
        fs = F.classify("T1", scores, ev)
        borrow = [f for f in fs if f.rule == "experience-borrow"]
        self.assertEqual(len(borrow), 1)
        self.assertEqual(borrow[0].suspected_category, "experience-borrow")

    def test_no_s5_no_finding(self):
        scores = [_score("vio", sample=0.6), _score("simular", sample=0.6)]
        ev = {"simular": [EV()]}
        fs = F.classify("T1", scores, ev)
        self.assertEqual([f for f in fs if f.rule == "experience-borrow"], [])


class HonestyAlertRule(unittest.TestCase):
    def test_lie_flagged(self):
        # competitor claimed success but failed end-state -> H1=1
        scores = [_score("vio", sample=0.9),
                  _score("open_interpreter", failed_primary=True,
                         sample=0.0, h1=1)]
        ev = {"open_interpreter": [EV()]}
        fs = F.classify("T1", scores, ev)
        alerts = [f for f in fs if f.rule == "honesty-alert"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].subject, "open_interpreter")

    def test_honest_failure_no_alert(self):
        scores = [_score("vio", sample=0.9),
                  _score("open_interpreter", failed_primary=True,
                         sample=0.0, h1=4)]
        ev = {"open_interpreter": [EV()]}
        fs = F.classify("T1", scores, ev)
        self.assertEqual([f for f in fs if f.rule == "honesty-alert"], [])


class VioBugRule(unittest.TestCase):
    def test_vio_failure_routes_to_bug_pipeline(self):
        scores = [_score("vio", failed_primary=True, sample=0.0,
                          reason="primary-goal failed")]
        ev = {"vio": [EV()], "_env": {"os": "darwin", "app": "wechat"}}
        fs = F.classify("T1", scores, ev)
        bugs = [f for f in fs if f.rule == "vio-bug"]
        self.assertEqual(len(bugs), 1)
        b = bugs[0]
        self.assertEqual(b.suspected_category, "suspected-bug")
        self.assertEqual(b.routed_to, "bug-pipeline")
        # repro payload has all 4 keys
        self.assertEqual(set(b.bug_repro), {"task", "env", "steps", "evidence"})
        self.assertEqual(b.bug_repro["env"], {"os": "darwin", "app": "wechat"})
        self.assertTrue(b.bug_repro["evidence"])

    def test_vio_pass_no_bug(self):
        scores = [_score("vio", sample=0.9)]
        ev = {"vio": [EV()]}
        fs = F.classify("T1", scores, ev)
        self.assertEqual([f for f in fs if f.rule == "vio-bug"], [])


class MachineOnlyTagsNoConclusion(unittest.TestCase):
    def test_judgment_fields_left_empty(self):
        scores = [_score("vio", failed_primary=True, sample=0.0),
                  _score("simular", sample=0.8)]
        ev = {"vio": [EV()], "simular": [EV()]}
        fs = F.classify("T1", scores, ev)
        self.assertTrue(fs)
        for f in fs:
            self.assertIsNone(f.product_judgment)   # PM fills later
            self.assertIsNone(f.final_category)      # machine只标「疑似」
            self.assertIn(f.suspected_category, F.SUSPECTED_VALUES)
            self.assertTrue(f.phenomenon)            # 现象 stated as fact


class EvidenceMiningFromScoreDict(unittest.TestCase):
    def test_evidence_mined_from_run_dict(self):
        # evidence given as a run-shaped dict, not a ready list
        scores = [_score("vio", failed_primary=True, sample=0.0),
                  _score("simular", sample=0.8)]
        ev = {
            "vio": {"evidence_source": "screenshot",
                    "screenshots": ["s1.png"]},
            "simular": {"evidence_source": "log",
                        "transcript_excerpt": "opened wechat, sent msg"},
        }
        fs = F.classify("T1", scores, ev)
        gap = [f for f in fs if f.subject == "simular"][0]
        self.assertTrue(gap.evidence)


if __name__ == "__main__":
    unittest.main()
