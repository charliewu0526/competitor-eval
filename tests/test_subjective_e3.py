"""E3: subjective aggregation — median + disagreement flag + scoring/defect split.

Run: python -m unittest tests.test_subjective_e3 -v

Acceptance (issue #16):
  - [5,4,1] -> median 4; range 4 >= 2 -> flagged
  - defect entries collected separately, never lower sample_score
  - a subjective score missing justification -> invalid (dropped)
  - S5: no process evidence -> S5 is None (not 0)
  - aggregation holds for 2 OR 3 reviewer scores

Seam-internal core logic, synthetic, OFFLINE — the review panel is swapped for
in-memory fakes (per PRD "适配器各自用假实现测").
"""
from __future__ import annotations
import unittest
from pipeline import aggregate as AGG
from pipeline import orchestrate
from pipeline.orchestrate import score_run
from pipeline.schema import RunRecord
from pipeline import objective as O
from tasks.T1_wechat_send import TASK, assertions


# --- helpers to build panelist dicts ----------------------------------------

def _pl(name, justify=("S1", "S2", "S3", "S4", "S5"), defects=None, **scores):
    """Build a panelist dict; only the dims in `justify` get a justification."""
    just = {d: f"{name} reason" for d in justify}
    return {"panelist": name, "justifications": just,
            "defects": list(defects or []), **scores}


SUCCESS = {"msg_received": True, "text_exact": True, "no_collateral": True}
FAILURE = {"msg_received": False, "text_exact": False, "no_collateral": True}


# =============================================================================
# Pure aggregation unit tests
# =============================================================================
class AggregateDimUnit(unittest.TestCase):
    def test_median_and_flag_5_4_1(self):
        panel = [_pl("a", S1=5), _pl("b", S1=4), _pl("c", S1=1)]
        agg = AGG.aggregate_dim(panel, "S1")
        self.assertEqual(agg["median"], 4)
        self.assertEqual(agg["range"], 4)
        self.assertTrue(agg["flagged"])
        self.assertEqual(agg["n"], 3)

    def test_no_disagreement_not_flagged(self):
        panel = [_pl("a", S1=4), _pl("b", S1=4)]
        agg = AGG.aggregate_dim(panel, "S1")
        self.assertEqual(agg["median"], 4)
        self.assertEqual(agg["range"], 0)
        self.assertFalse(agg["flagged"])

    def test_range_exactly_two_flags(self):
        panel = [_pl("a", S1=5), _pl("b", S1=3)]
        agg = AGG.aggregate_dim(panel, "S1")
        self.assertTrue(agg["flagged"])  # range 2 >= threshold 2

    def test_two_scores_aggregate(self):
        panel = [_pl("a", S2=5), _pl("b", S2=3)]
        self.assertEqual(AGG.aggregate_dim(panel, "S2")["median"], 4)

    def test_three_scores_aggregate(self):
        panel = [_pl("a", S2=5), _pl("b", S2=4), _pl("c", S2=1)]
        self.assertEqual(AGG.aggregate_dim(panel, "S2")["median"], 4)


class JustificationGating(unittest.TestCase):
    def test_unjustified_score_dropped(self):
        # c scores S1 but provides NO justification for it -> dropped.
        panel = [_pl("a", S1=4), _pl("b", S1=4),
                 _pl("c", justify=("S2",), S1=1)]  # S1 unjustified
        agg = AGG.aggregate_dim(panel, "S1")
        self.assertEqual(agg["n"], 2)          # only a + b counted
        self.assertEqual(agg["scores"], [4.0, 4.0])
        self.assertEqual(agg["median"], 4)

    def test_all_unjustified_yields_none(self):
        panel = [_pl("a", justify=(), S1=5), _pl("b", justify=(), S1=1)]
        agg = AGG.aggregate_dim(panel, "S1")
        self.assertIsNone(agg["median"])
        self.assertEqual(agg["n"], 0)
        self.assertFalse(agg["flagged"])

    def test_bool_and_out_of_range_rejected(self):
        panel = [_pl("a", S1=True), _pl("b", S1=9), _pl("c", S1=4)]
        agg = AGG.aggregate_dim(panel, "S1")
        self.assertEqual(agg["n"], 1)          # only the valid 4
        self.assertEqual(agg["median"], 4)


class DefectCollection(unittest.TestCase):
    def test_defects_collected_from_all(self):
        panel = [_pl("deepseek", S1=5, defects=["typo in message", "slow"]),
                 _pl("claude", S1=5)]
        defects = AGG.collect_defects(panel)
        self.assertEqual(len(defects), 2)
        self.assertEqual({d["by"] for d in defects}, {"deepseek"})

    def test_dict_defect_with_dim(self):
        panel = [_pl("a", S1=5, defects=[{"desc": "missed edge case", "dim": "S3"}])]
        defects = AGG.collect_defects(panel)
        self.assertEqual(defects[0]["desc"], "missed edge case")
        self.assertEqual(defects[0]["dim"], "S3")


class S5EvidenceGating(unittest.TestCase):
    def test_s5_aggregated_with_evidence(self):
        panel = [_pl("a", S5=5), _pl("b", S5=3)]
        agg = AGG.aggregate_subjective(panel, {"has_process_evidence": True})
        self.assertEqual(agg["medians"]["S5"], 4)

    def test_s5_none_without_evidence(self):
        panel = [_pl("a", S5=5), _pl("b", S5=3)]
        agg = AGG.aggregate_subjective(panel, {"has_process_evidence": False})
        self.assertIsNone(agg["medians"]["S5"])     # None, NOT 0
        self.assertEqual(agg["per_dim"]["S5"]["reason"], "no process evidence")

    def test_evidence_inferred_from_transcript(self):
        self.assertTrue(AGG.has_process_evidence({"transcript_excerpt": "opened app, clicked"}))
        self.assertTrue(AGG.has_process_evidence({"evidence_source": "screenshot"}))
        self.assertFalse(AGG.has_process_evidence({}))
        self.assertFalse(AGG.has_process_evidence({"evidence_source": "unavailable"}))


class WeightedCapability(unittest.TestCase):
    def test_excludes_s5(self):
        from pipeline.review_prompt import DIMENSIONS
        medians = {"S1": 5, "S2": 5, "S3": 5, "S4": 5, "S5": 1}
        # all S1-S4 = 5 -> capability factor 1.0 regardless of S5.
        self.assertEqual(AGG.weighted_capability(medians, DIMENSIONS), 1.0)

    def test_renormalizes_missing_dim(self):
        from pipeline.review_prompt import DIMENSIONS
        # only S1 present at 5 -> renormalized to full weight -> 1.0
        medians = {"S1": 5, "S2": None, "S3": None, "S4": None, "S5": None}
        self.assertEqual(AGG.weighted_capability(medians, DIMENSIONS), 1.0)

    def test_all_none_returns_none(self):
        from pipeline.review_prompt import DIMENSIONS
        medians = {d: None for d in ("S1", "S2", "S3", "S4", "S5")}
        self.assertIsNone(AGG.weighted_capability(medians, DIMENSIONS))


# =============================================================================
# Seam-level tests through score_run (review panel faked)
# =============================================================================
def _run(**kw) -> RunRecord:
    base = dict(task_id=TASK.task_id, product="vio", run_idx=1, gate="native-operable")
    base.update(kw)
    return RunRecord(**base)


def _from_endstate(ctx: dict, **rr_kw) -> RunRecord:
    res = O.run_assertions(assertions(), ctx)
    return _run(objective_passed=res["passed"], objective_total=res["total"],
                objective_failed_primary=res["failed_primary"], **rr_kw)


class _SeamCase(unittest.TestCase):
    """Install a fake panel via PANELISTS name resolution."""
    panel_factory = None  # set per-test

    def setUp(self):
        self._orig = (orchestrate.review_gemini, orchestrate.review_claude)

    def tearDown(self):
        orchestrate.review_gemini, orchestrate.review_claude = self._orig

    def _install(self, p0, p1):
        orchestrate.review_gemini = lambda prompt: p0
        orchestrate.review_claude = lambda prompt: p1


class ScoreRunAggregation(_SeamCase):
    def test_disagreement_flagged_in_output(self):
        # S1: 5 vs 1 -> range 4 flagged; others agree.
        self._install(_pl("gemini", S1=5, S2=4, S3=4, S4=4, S5=4),
                      _pl("claude", S1=1, S2=4, S3=4, S4=4, S5=4))
        sc = score_run(TASK, _from_endstate(SUCCESS, transcript_excerpt="did steps"), {})
        self.assertIn("S1", sc["disagreement_flagged"])
        self.assertEqual(sc["subjective"]["S1"], 3)   # median(5,1)=3
        self.assertGreater(sc["sample_score"], 0.0)

    def test_defect_does_not_lower_score(self):
        # Two runs, identical scores; one panelist reports a defect on run B.
        no_def = (_pl("gemini", S1=5, S2=5, S3=5, S4=5, S5=5),
                  _pl("claude", S1=5, S2=5, S3=5, S4=5, S5=5))
        with_def = (_pl("gemini", S1=5, S2=5, S3=5, S4=5, S5=5,
                        defects=["found a subtle bug but capability still 5"]),
                    _pl("claude", S1=5, S2=5, S3=5, S4=5, S5=5))
        self._install(*no_def)
        a = score_run(TASK, _from_endstate(SUCCESS, transcript_excerpt="x"), {})
        self._install(*with_def)
        b = score_run(TASK, _from_endstate(SUCCESS, transcript_excerpt="x"), {})
        self.assertEqual(a["sample_score"], b["sample_score"])  # 找错 ≠ 压分
        self.assertEqual(len(a["defects"]), 0)
        self.assertEqual(len(b["defects"]), 1)

    def test_s5_none_without_process_evidence(self):
        self._install(_pl("gemini", S1=4, S2=4, S3=4, S4=4, S5=5),
                      _pl("claude", S1=4, S2=4, S3=4, S4=4, S5=5))
        # No transcript, no screenshots, evidence unavailable -> S5 None.
        sc = score_run(TASK, _from_endstate(SUCCESS), {})
        self.assertIsNone(sc["subjective"]["S5"])
        self.assertGreater(sc["sample_score"], 0.0)  # capability still scored

    def test_s5_present_with_evidence(self):
        self._install(_pl("gemini", S1=4, S2=4, S3=4, S4=4, S5=5),
                      _pl("claude", S1=4, S2=4, S3=4, S4=4, S5=3))
        sc = score_run(TASK, _from_endstate(SUCCESS, transcript_excerpt="opened, clicked, sent"), {})
        self.assertEqual(sc["subjective"]["S5"], 4)  # median(5,3)

    def test_three_panelists(self):
        # Temporarily extend the panel to 3 to prove N-model generalization.
        orig = orchestrate.PANELISTS
        orchestrate.review_deepseek = lambda prompt: _pl("deepseek", S1=1, S2=4, S3=4, S4=4, S5=4)
        orchestrate.PANELISTS = ("review_gemini", "review_claude", "review_deepseek")
        try:
            self._install(_pl("gemini", S1=5, S2=4, S3=4, S4=4, S5=4),
                          _pl("claude", S1=4, S2=4, S3=4, S4=4, S5=4))
            sc = score_run(TASK, _from_endstate(SUCCESS, transcript_excerpt="x"), {})
            self.assertEqual(sc["subjective"]["S1"], 4)   # median(5,4,1)=4
            self.assertIn("S1", sc["disagreement_flagged"])  # range 4
        finally:
            orchestrate.PANELISTS = orig


class OIRegressionUnbroken(_SeamCase):
    """E3 must not break the 立身之本 case: primary fail -> 0, subjective skipped."""
    def test_primary_fail_still_zero(self):
        self._install(_pl("gemini", S1=5, S2=5, S3=5, S4=5, S5=5),
                      _pl("claude", S1=5, S2=5, S3=5, S4=5, S5=5))
        sc = score_run(TASK, _from_endstate(FAILURE, claimed_success=True), {})
        self.assertEqual(sc["sample_score"], 0.0)
        self.assertIsNone(sc["subjective"])
        self.assertNotIn("panel", sc)  # panel never invoked


if __name__ == "__main__":
    unittest.main()
