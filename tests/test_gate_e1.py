"""E1: GATE derivation — capability-domain × task-requirement, derived at run time.

Run: python -m unittest tests.test_gate_e1 -v

Acceptance (issue #E1):
  - capability=false + desktop task  -> cannot-reach, AND excluded from leaderboard
  - capability=true  + desktop task  -> native-operable, participates normally
  - cannot-reach does NOT produce a phantom sample_score=0 ("假失败")
  - the SAME competitor derives DIFFERENT gates on a desktop task vs a non-desktop task

Pure seam-internal logic: synthetic competitors/tasks/RunRecords only, no API/IO.
"""
from __future__ import annotations
import unittest
from pipeline.gate import (
    derive_gate, gate_for, is_fair, is_excluded, filter_leaderboard_rows,
)
from pipeline.schema import TaskSpec, RunRecord, GATE_VALUES
from pipeline.registry import Competitor
from pipeline.orchestrate import score_run


# --- synthetic fixtures (no real task/competitor needed) ---
def _task(requires_local_desktop: bool, task_id="T") -> TaskSpec:
    return TaskSpec(task_id=task_id, domain="1", app="wechat",
                    prompt="do the thing", core_assertions=["primary"],
                    requires_local_desktop=requires_local_desktop)


DESKTOP_TASK = _task(True, "desktop")
API_TASK = _task(False, "api")

DESKTOP_AGENT = Competitor("vio", "Violoop", can_operate_local_desktop=True)
CLOUD_AGENT = Competitor("manus", "Manus", can_operate_local_desktop=False)


class DeriveGateTruthTable(unittest.TestCase):
    """The 2×2 cross. derive_gate only ever returns a valid GATE_VALUES member."""

    def test_desktop_task_capable_is_native(self):
        self.assertEqual(derive_gate(True, True), "native-operable")

    def test_desktop_task_incapable_is_cannot_reach(self):
        self.assertEqual(derive_gate(False, True), "cannot-reach")

    def test_nondesktop_task_capable_is_native(self):
        self.assertEqual(derive_gate(True, False), "native-operable")

    def test_nondesktop_task_incapable_is_cross_layer(self):
        self.assertEqual(derive_gate(False, False), "api-or-integration")

    def test_all_outputs_are_valid_gates(self):
        for cap in (True, False):
            for req in (True, False):
                self.assertIn(derive_gate(cap, req), GATE_VALUES)


class GateForCompetitorTask(unittest.TestCase):
    """gate_for wraps a Competitor (F2) × TaskSpec (F1)."""

    def test_cloud_on_desktop_task_cannot_reach(self):
        self.assertEqual(gate_for(CLOUD_AGENT, DESKTOP_TASK), "cannot-reach")

    def test_desktop_agent_on_desktop_task_native(self):
        self.assertEqual(gate_for(DESKTOP_AGENT, DESKTOP_TASK), "native-operable")

    def test_same_competitor_different_tasks_different_gates(self):
        """Acceptance: gate is NOT pinned to the competitor — it's derived per task."""
        g_desktop = gate_for(CLOUD_AGENT, DESKTOP_TASK)      # can't reach the app
        g_api = gate_for(CLOUD_AGENT, API_TASK)              # reachable, cross-layer
        self.assertEqual(g_desktop, "cannot-reach")
        self.assertEqual(g_api, "api-or-integration")
        self.assertNotEqual(g_desktop, g_api)


class LeaderboardExclusion(unittest.TestCase):
    """cannot-reach is dropped from ranking; it must not become an unfair 0."""

    def test_is_fair_only_native(self):
        self.assertTrue(is_fair("native-operable"))
        self.assertFalse(is_fair("cannot-reach"))
        self.assertFalse(is_fair("api-or-integration"))

    def test_is_excluded_only_cannot_reach(self):
        self.assertTrue(is_excluded("cannot-reach"))
        self.assertFalse(is_excluded("native-operable"))
        self.assertFalse(is_excluded("api-or-integration"))

    def test_invalid_gate_rejected(self):
        with self.assertRaises(ValueError):
            is_fair("teleport")

    def test_filter_drops_cannot_reach_keeps_others(self):
        rows = [
            {"product": "vio", "gate": "native-operable"},
            {"product": "manus", "gate": "cannot-reach"},
            {"product": "operator", "gate": "api-or-integration"},
        ]
        kept = filter_leaderboard_rows(rows)
        ids = [r["product"] for r in kept]
        self.assertIn("vio", ids)
        self.assertIn("operator", ids)          # cross-layer stays (own track)
        self.assertNotIn("manus", ids)          # cannot-reach dropped
        self.assertEqual(len(rows), 3)          # input untouched


class CannotReachIsNotAFakeZero(unittest.TestCase):
    """Acceptance: derived cannot-reach -> score_run yields NO sample_score.

    A cloud agent that can't reach a desktop app must be 'not participating',
    never recorded as a 0.0 capability failure (which would wrongly drag its
    rank / inflate Vio's lead).
    """

    def test_derived_cannot_reach_has_no_sample_score(self):
        gate = gate_for(CLOUD_AGENT, DESKTOP_TASK)
        self.assertEqual(gate, "cannot-reach")
        rr = RunRecord(task_id=DESKTOP_TASK.task_id, product="manus",
                       run_idx=1, gate=gate, objective_failed_primary=True)
        sc = score_run(DESKTOP_TASK, rr, {})
        self.assertFalse(sc["scored"])
        self.assertEqual(sc["reason"], "cannot-reach")
        self.assertTrue(sc["cross_layer"])
        self.assertNotIn("sample_score", sc)     # NO phantom 0
        # and such a row is dropped before ranking
        self.assertEqual(filter_leaderboard_rows([sc]), [])

    def test_derived_native_participates_with_score(self):
        gate = gate_for(DESKTOP_AGENT, DESKTOP_TASK)
        self.assertEqual(gate, "native-operable")
        # primary failed -> a REAL 0 (it tried and failed), distinct from cannot-reach
        rr = RunRecord(task_id=DESKTOP_TASK.task_id, product="vio",
                       run_idx=1, gate=gate, objective_failed_primary=True)
        sc = score_run(DESKTOP_TASK, rr, {})
        self.assertTrue(sc["scored"])
        self.assertEqual(sc["sample_score"], 0.0)   # a fair, earned 0
        self.assertEqual(filter_leaderboard_rows([sc]), [sc])  # stays in ranking


if __name__ == "__main__":
    unittest.main()
