"""E2: Objective assertion layer — completion is judged by END-STATE facts only.

Seam under test: orchestrate.score_run(RunRecord -> score). Completion (primary
goal met?) is decided ONLY from objective end-state fields written by the
objective layer; it NEVER reads claimed_success or transcript/log text.

Run: python -m unittest tests.test_objective_e2 -v

Acceptance (issue #E2):
  - primary fail  -> sample_score=0 AND subjective skipped
  - primary pass  -> enters subjective review
  - completion reads end-state only, never claimed_success / log text
  - 3 end-state cases: success / failure / missing-evidence

E2 is seam-internal core logic and must NEVER hit the network. Per PRD
"适配器各自用假实现测", the review panel is swapped for an in-memory fake.
"""
from __future__ import annotations
import unittest
from pipeline import orchestrate
from pipeline.schema import RunRecord
from pipeline import objective as O
from pipeline.orchestrate import score_run
from tasks.T1_wechat_send import TASK, assertions


def _fake_panelist(name):
    fixed = {"S1": 4, "S2": 4, "S3": 4, "S4": 4, "S5": 4}
    just = {d: "fake" for d in ("S1", "S2", "S3", "S4", "S5")}
    def _review(prompt):
        return {"panelist": name, "dry_run": True,
                "justifications": just, "defects": [], **fixed}
    return _review


def _run(**kw) -> RunRecord:
    base = dict(task_id=TASK.task_id, product="vio", run_idx=1, gate="native-operable")
    base.update(kw)
    return RunRecord(**base)


def _from_endstate(ctx: dict, **rr_kw) -> RunRecord:
    """Build a RunRecord whose objective_* come purely from end-state ctx flags."""
    res = O.run_assertions(assertions(), ctx)
    return _run(objective_passed=res["passed"], objective_total=res["total"],
                objective_failed_primary=res["failed_primary"], **rr_kw)


# end-state contexts for T1 (operator-verified flags)
SUCCESS = {"msg_received": True, "text_exact": True, "no_collateral": True}
FAILURE = {"msg_received": False, "text_exact": False, "no_collateral": True}
MISSING = {}  # no end-state evidence recorded at all


class _SeamCase(unittest.TestCase):
    """Swap the review adapter for an in-memory fake so the seam stays offline."""

    def setUp(self):
        self._orig = (orchestrate.review_gemini, orchestrate.review_claude)
        orchestrate.review_gemini = _fake_panelist("gemini")
        orchestrate.review_claude = _fake_panelist("claude")

    def tearDown(self):
        orchestrate.review_gemini, orchestrate.review_claude = self._orig


class PrimaryFailSkipsSubjective(_SeamCase):
    def test_primary_fail_scores_zero_and_skips_subjective(self):
        sc = score_run(TASK, _from_endstate(FAILURE), {})
        self.assertTrue(sc["objective_failed_primary"])
        self.assertEqual(sc["sample_score"], 0.0)
        self.assertIsNone(sc["subjective"])          # subjective skipped
        self.assertNotIn("panel", sc)                # panel never invoked


class PrimaryPassEntersSubjective(_SeamCase):
    def test_primary_pass_enters_subjective(self):
        sc = score_run(TASK, _from_endstate(SUCCESS), {})
        self.assertFalse(sc["objective_failed_primary"])
        self.assertIsNotNone(sc["subjective"])       # subjective ran
        self.assertIn("panel", sc)
        self.assertGreater(sc["sample_score"], 0.0)


class CompletionReadsEndStateOnly(_SeamCase):
    """The decisive E2 guarantee: claimed_success / log text must NOT sway completion."""

    def test_lying_self_report_cannot_fake_success(self):
        # End-state FAILS, but the agent loudly claims success in self-report + log.
        # Replicates the OI "TASK COMPLETE" case — must still score 0, skip subjective.
        sc = score_run(TASK, _from_endstate(
            FAILURE, claimed_success=True,
            transcript_excerpt="TASK COMPLETE -- message sent successfully!"), {})
        self.assertEqual(sc["sample_score"], 0.0)
        self.assertIsNone(sc["subjective"])

    def test_modest_self_report_does_not_block_real_success(self):
        # End-state PASSES, yet agent never claims success / leaves an empty log.
        # Completion must still recognize success purely from end-state.
        sc = score_run(TASK, _from_endstate(
            SUCCESS, claimed_success=False, transcript_excerpt=""), {})
        self.assertFalse(sc["objective_failed_primary"])
        self.assertIsNotNone(sc["subjective"])
        self.assertGreater(sc["sample_score"], 0.0)

    def test_completion_invariant_under_claimed_success_flip(self):
        # Flipping claimed_success / log on the SAME end-state must not change verdict.
        a = score_run(TASK, _from_endstate(SUCCESS, claimed_success=False,
                                            transcript_excerpt=""), {})
        b = score_run(TASK, _from_endstate(SUCCESS, claimed_success=True,
                                            transcript_excerpt="done done done"), {})
        self.assertEqual(a["objective_failed_primary"], b["objective_failed_primary"])
        self.assertEqual(a["sample_score"] > 0, b["sample_score"] > 0)


class ThreeEndStateCases(_SeamCase):
    """末态成功 / 末态失败 / 末态缺证据."""

    def test_end_state_success(self):
        res = O.run_assertions(assertions(), SUCCESS)
        self.assertFalse(res["failed_primary"])
        self.assertEqual(res["passed"], res["total"])

    def test_end_state_failure(self):
        res = O.run_assertions(assertions(), FAILURE)
        self.assertTrue(res["failed_primary"])

    def test_end_state_missing_evidence_is_not_success(self):
        # No evidence recorded -> primary cannot be confirmed -> treated as fail,
        # NOT silently passed. "拿不到" must never masquerade as "完成".
        res = O.run_assertions(assertions(), MISSING)
        self.assertTrue(res["failed_primary"])
        self.assertEqual(res["passed"], 0)
        sc = score_run(TASK, _from_endstate(MISSING), {})
        self.assertEqual(sc["sample_score"], 0.0)
        self.assertIsNone(sc["subjective"])


if __name__ == "__main__":
    unittest.main()
