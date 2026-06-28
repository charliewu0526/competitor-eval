"""A1 (#19): three-model review adapter — DeepSeek + GLM + Claude.

Run: python -m unittest tests.test_review_adapter_a1 -v

Acceptance (issue #19), all OFFLINE — no network:
  - production clients return the contract dict shape (verified via missing-key
    DRY-RUN stub path; real API calls are NOT made in tests)
  - in-memory fake panel returns fixed three scores, no network
  - both impls satisfy the SAME contract (a shared contract assertion runs over
    fake panelists AND stub-mode production panelists)
  - panel members are configurable (REVIEW_PANEL env / PANELISTS swap) without
    touching aggregation
  - a return missing justification is treated as invalid (dropped) — aligns w/ E3
"""
from __future__ import annotations
import os
import unittest

from pipeline import review_client as RC
from pipeline import review_fakes as RF
from pipeline import aggregate as AGG
from pipeline import orchestrate
from pipeline.orchestrate import score_run
from pipeline.schema import RunRecord
from pipeline import objective as O
from tasks.T1_wechat_send import TASK, assertions

_DIMS = ("S1", "S2", "S3", "S4", "S5")
SUCCESS = {"msg_received": True, "text_exact": True, "no_collateral": True}


def _assert_contract(tc: unittest.TestCase, r: dict):
    """The shared adapter contract every panelist (prod or fake) must satisfy."""
    tc.assertIn("panelist", r)
    tc.assertIsInstance(r["panelist"], str)
    tc.assertIn("dry_run", r)
    # error returns are allowed but must still name the panelist
    if "error" in r:
        return
    for d in ("S1", "S2", "S3", "S4"):
        tc.assertIn(d, r)
        tc.assertIsInstance(r[d], int)
        tc.assertTrue(1 <= r[d] <= 5)
    tc.assertIn("S5", r)  # may be None
    tc.assertIn("justifications", r)
    tc.assertIsInstance(r["justifications"], dict)
    tc.assertIn("defects", r)
    tc.assertIsInstance(r["defects"], list)


# =============================================================================
# Production clients — exercised in DRY-RUN (no keys) so no network is hit.
# =============================================================================
class ProductionStubContract(unittest.TestCase):
    """With keys absent, each production client returns a valid stub dict."""

    def setUp(self):
        # Strip every panel key so all clients fall to their _stub path.
        self._saved = {k: os.environ.pop(k, None) for k in (
            "DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY",
            "CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "AWS_BEARER_TOKEN_BEDROCK",
            "GEMINI_API_KEY")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_deepseek_stub_contract(self):
        r = RC.review_deepseek("p")
        self.assertEqual(r["panelist"], "deepseek")
        self.assertTrue(r["dry_run"])
        _assert_contract(self, r)

    def test_glm_stub_contract(self):
        r = RC.review_glm("p")
        self.assertEqual(r["panelist"], "glm")
        self.assertTrue(r["dry_run"])
        _assert_contract(self, r)

    def test_claude_stub_contract(self):
        r = RC.review_claude("p")
        self.assertEqual(r["panelist"], "claude")
        self.assertTrue(r["dry_run"])
        _assert_contract(self, r)


# =============================================================================
# In-memory fake panel — fixed scores, offline.
# =============================================================================
class FakePanelContract(unittest.TestCase):
    def test_each_fake_satisfies_contract(self):
        for fn in RF.FAKE_PANEL.values():
            _assert_contract(self, fn("ignored prompt"))

    def test_fake_returns_fixed_scores(self):
        r = RF.fake_claude("anything")
        self.assertEqual(r["S1"], 5)
        self.assertTrue(r["dry_run"])
        # deterministic: same call -> same scores
        self.assertEqual(RF.fake_claude("other prompt")["S1"], 5)

    def test_strict_panelist_carries_defect_not_lower_score(self):
        # DeepSeek fake reports a defect while still scoring honestly (找错≠压分).
        r = RF.fake_deepseek("x")
        self.assertEqual(len(r["defects"]), 1)
        self.assertTrue(all(1 <= r[d] <= 5 for d in ("S1", "S2", "S3", "S4")))


# =============================================================================
# Same-contract proof: fake AND stub-prod panelists feed aggregation identically.
# =============================================================================
class SharedContractThroughAggregation(unittest.TestCase):
    def test_fake_panel_aggregates(self):
        panel = [fn("p") for fn in RF.FAKE_PANEL.values()]
        agg = AGG.aggregate_subjective(panel, {"has_process_evidence": True})
        for d in _DIMS:
            self.assertIsNotNone(agg["medians"][d])
        # DeepSeek's lone defect is collected separately.
        self.assertEqual(len(agg["defects"]), 1)

    def test_missing_justification_dropped(self):
        # A panelist that emits a score but no justification for S2 -> S2 dropped.
        bad = RF.make_fake("glm", {"S2": 1}, justify=("S1", "S3", "S4", "S5"))
        good = RF.make_fake("claude", {"S2": 4})
        agg = AGG.aggregate_dim([bad("p"), good("p")], "S2")
        self.assertEqual(agg["n"], 1)          # only the justified one counts
        self.assertEqual(agg["scores"], [4.0])


# =============================================================================
# Panel configurability — swap members without touching aggregation.
# =============================================================================
class PanelConfigurable(unittest.TestCase):
    def setUp(self):
        self._orig_panel = orchestrate.PANELISTS
        self._saved = {}
        for n, fn in RF.FAKE_PANEL.items():
            self._saved[n] = getattr(orchestrate, n, None)
            setattr(orchestrate, n, fn)

    def tearDown(self):
        orchestrate.PANELISTS = self._orig_panel
        for n, v in self._saved.items():
            if v is None:
                if hasattr(orchestrate, n):
                    delattr(orchestrate, n)
            else:
                setattr(orchestrate, n, v)

    def _run(self):
        res = O.run_assertions(assertions(), SUCCESS)
        rr = RunRecord(task_id=TASK.task_id, product="vio", run_idx=1,
                       gate="native-operable", objective_passed=res["passed"],
                       objective_total=res["total"],
                       objective_failed_primary=res["failed_primary"],
                       transcript_excerpt="opened, did steps, sent")
        return score_run(TASK, rr, {})

    def test_default_panel_is_usable_members(self):
        # Current usable default = DeepSeek + Gemini (GLM rate-limited, Claude
        # out of credit). All members must be known panelist names so the
        # globals()[...] resolution in _run_panel works.
        self.assertEqual(self._orig_panel, ("review_deepseek", "review_gemini"))
        for name in self._orig_panel:
            self.assertTrue(hasattr(orchestrate, name))

    def test_three_member_panel_scores(self):
        orchestrate.PANELISTS = ("review_deepseek", "review_glm", "review_claude")
        sc = self._run()
        self.assertTrue(sc["scored"])
        self.assertEqual(len(sc["panel"]), 3)
        self.assertGreater(sc["sample_score"], 0.0)

    def test_swap_to_two_members_without_core_change(self):
        orchestrate.PANELISTS = ("review_glm", "review_claude")
        sc = self._run()
        self.assertEqual(len(sc["panel"]), 2)
        self.assertGreater(sc["sample_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
