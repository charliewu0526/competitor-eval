"""F1: TaskSpec / RunRecord v2 schema tests. Stdlib unittest (no pytest dep).

Run: python -m unittest tests.test_schema_v2 -v
Covers acceptance: enum rejection, heavy=>known_edge_cases, back-compat load.
"""
from __future__ import annotations
import json, tempfile, unittest, pathlib
from pipeline.schema import TaskSpec, RunRecord, save, load_json


def _task(**kw):
    base = dict(task_id="T1", domain="1", app="wechat", prompt="p", core_assertions=["primary"])
    base.update(kw)
    return TaskSpec(**base)


def _run(**kw):
    base = dict(task_id="T1", product="vio", run_idx=1, gate="native-operable")
    base.update(kw)
    return RunRecord(**base)


class TaskSpecV2(unittest.TestCase):
    def test_defaults_valid(self):
        t = _task()
        self.assertEqual(t.tier, "core-common")
        self.assertEqual(t.kind, "task-exam")
        self.assertTrue(t.requires_local_desktop)
        self.assertEqual(t.dirty_data_level, "none")
        self.assertIsNone(t.dirty_data_level_suggested)

    def test_all_new_fields_settable(self):
        t = _task(tier="vio-key", kind="capability-probe", requires_local_desktop=False,
                  dirty_data_level="light", dirty_data_level_suggested="heavy")
        self.assertEqual((t.tier, t.kind, t.dirty_data_level, t.dirty_data_level_suggested),
                         ("vio-key", "capability-probe", "light", "heavy"))

    def test_bad_tier_rejected(self):
        with self.assertRaises(ValueError):
            _task(tier="frontier")

    def test_bad_kind_rejected(self):
        with self.assertRaises(ValueError):
            _task(kind="exam")

    def test_bad_dirty_level_rejected(self):
        with self.assertRaises(ValueError):
            _task(dirty_data_level="filthy")

    def test_bad_suggested_rejected(self):
        with self.assertRaises(ValueError):
            _task(dirty_data_level_suggested="filthy")

    def test_heavy_requires_edge_cases(self):
        with self.assertRaises(ValueError):
            _task(dirty_data_level="heavy")  # no known_edge_cases

    def test_heavy_with_edge_cases_ok(self):
        t = _task(dirty_data_level="heavy", known_edge_cases=["amount mismatch"])
        self.assertEqual(t.known_edge_cases, ["amount mismatch"])

    def test_suggested_and_final_coexist(self):
        # AI suggests heavy, human/verifier sets final light -> both kept (story 32)
        t = _task(dirty_data_level="light", dirty_data_level_suggested="heavy")
        self.assertNotEqual(t.dirty_data_level, t.dirty_data_level_suggested)


class RunRecordV2(unittest.TestCase):
    def test_cost_evidence_defaults(self):
        r = _run()
        self.assertEqual(r.cost_input_tokens, 0)
        self.assertEqual(r.cost_output_tokens, 0)
        self.assertEqual(r.cost_model_calls, 0)
        self.assertIsNone(r.cost_usd)
        self.assertEqual(r.cost_source, "unavailable")
        self.assertEqual(r.evidence_source, "unavailable")
        self.assertIsNone(r.claimed_success)

    def test_all_new_fields_settable(self):
        r = _run(cost_input_tokens=120, cost_output_tokens=30, cost_model_calls=2,
                 cost_usd=0.0042, cost_source="self-report", evidence_source="log",
                 claimed_success=True)
        self.assertEqual(r.cost_usd, 0.0042)
        self.assertEqual(r.cost_source, "self-report")
        self.assertEqual(r.evidence_source, "log")
        self.assertTrue(r.claimed_success)

    def test_bad_gate_rejected(self):
        with self.assertRaises(ValueError):
            _run(gate="teleport")

    def test_bad_cost_source_rejected(self):
        with self.assertRaises(ValueError):
            _run(cost_source="guessed")

    def test_bad_evidence_source_rejected(self):
        with self.assertRaises(ValueError):
            _run(evidence_source="vibes")


class BackCompat(unittest.TestCase):
    def test_old_runrecord_dict_still_loads(self):
        # A pre-v2 RunRecord JSON (no cost/evidence/claimed fields) must load.
        old = {"task_id": "T1", "product": "open_interpreter", "run_idx": 1,
               "gate": "native-operable", "objective_passed": 0, "objective_total": 3,
               "objective_failed_primary": True, "transcript_excerpt": "TASK COMPLETE",
               "env_meta": {"model": "gpt-4"}}
        r = RunRecord(**old)
        self.assertEqual(r.cost_source, "unavailable")
        self.assertIsNone(r.claimed_success)
        self.assertAlmostEqual(r.objective_ratio, 0.0)

    def test_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "r.json"
            r = _run(cost_usd=0.01, cost_source="proxy", evidence_source="screenshot",
                     claimed_success=False)
            save(r, str(p))
            back = load_json(str(p))
            self.assertEqual(back["cost_source"], "proxy")
            self.assertEqual(back["evidence_source"], "screenshot")
            self.assertFalse(back["claimed_success"])
            # reconstruct from disk -> validates again
            RunRecord(**back)


if __name__ == "__main__":
    unittest.main()
