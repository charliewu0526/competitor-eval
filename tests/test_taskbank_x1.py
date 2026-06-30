"""X1: task-bank directory standard + dirty-data declaration regime.

Run: python -m unittest tests.test_taskbank_x1 -v
Covers acceptance: fixed layout, meta.json single source field-consistent with
F1, heavy=>known_edge_cases, suggested/final two-source rule, T1 sample valid.
"""
from __future__ import annotations
import json, tempfile, unittest, pathlib, shutil
from pipeline import taskbank as TB

ROOT = pathlib.Path(__file__).resolve().parent.parent
T1_DIR = ROOT / "tasks" / "T1-wechat-send-001"


def _meta(**spec_over):
    spec = dict(task_id="TX", domain="1", app="wechat", prompt="p",
                core_assertions=["primary"], expects_file=False,
                tier="core-common", kind="task-exam", requires_local_desktop=True,
                dirty_data_level="none", dirty_data_level_suggested=None,
                known_edge_cases=[],
                capability_domain="wechat-im", task_nature="simple")
    spec.update(spec_over)
    return {"schema": "taskbank-v1", "task_spec": spec,
            "dirty_data": {"suggested_by": "ai:generator", "final_by": "human:charlie"}}


class MetaContract(unittest.TestCase):
    def test_clean_meta_valid(self):
        self.assertEqual(TB.validate_meta(_meta()), [])

    def test_unknown_field_is_drift(self):
        m = _meta(); m["task_spec"]["frontier"] = True
        probs = TB.validate_meta(m)
        self.assertTrue(any("unknown fields" in p for p in probs))

    def test_missing_required_field(self):
        m = _meta(); del m["task_spec"]["task_id"]
        probs = TB.validate_meta(m)
        self.assertTrue(any("missing required" in p for p in probs))

    def test_bad_enum_caught_via_schema(self):
        probs = TB.validate_meta(_meta(tier="frontier"))
        self.assertTrue(any("invalid per F1 schema" in p for p in probs))


class DirtyDataRegime(unittest.TestCase):
    def test_heavy_requires_edge_cases(self):
        # F1 schema raises -> surfaced as invalid
        probs = TB.validate_meta(_meta(tier="stress", dirty_data_level="heavy"))
        self.assertTrue(any("known_edge_cases" in p for p in probs))

    def test_heavy_with_edge_cases_ok(self):
        m = _meta(tier="stress", dirty_data_level="heavy",
                  dirty_data_level_suggested="heavy",
                  known_edge_cases=["amount mismatch"])
        self.assertEqual(TB.validate_meta(m), [])

    def test_stress_with_none_rejected(self):
        probs = TB.validate_meta(_meta(tier="stress", dirty_data_level="none"))
        self.assertTrue(any("stress" in p and "none" in p for p in probs))

    def test_core_common_heavy_flagged(self):
        m = _meta(tier="core-common", dirty_data_level="heavy",
                  dirty_data_level_suggested="heavy", known_edge_cases=["x"])
        probs = TB.validate_meta(m)
        self.assertTrue(any("core-common" in p for p in probs))


class TwoSourceProvenance(unittest.TestCase):
    def test_same_source_rejected(self):
        m = _meta(dirty_data_level_suggested="none")
        m["dirty_data"] = {"suggested_by": "ai:gen", "final_by": "ai:gen"}
        probs = TB.validate_meta(m)
        self.assertTrue(any("self-certify" in p or "suggested_by == final_by" in p
                            for p in probs))

    def test_missing_final_by_rejected(self):
        m = _meta(dirty_data_level_suggested="none")
        m["dirty_data"] = {"suggested_by": "ai:gen"}
        probs = TB.validate_meta(m)
        self.assertTrue(any("final_by missing" in p for p in probs))

    def test_different_sources_ok(self):
        m = _meta(dirty_data_level_suggested="light", dirty_data_level="light")
        m["dirty_data"] = {"suggested_by": "ai:gen", "final_by": "human:charlie"}
        self.assertEqual(TB.validate_meta(m), [])


class DirLayout(unittest.TestCase):
    def _make(self, d):
        for f in TB.REQUIRED_FILES:
            (d / f).write_text("{}" if f == "meta.json" else "x")
        (d / "meta.json").write_text(json.dumps(_meta(task_id=d.name)))
        for sub in TB.REQUIRED_DIRS:
            (d / sub).mkdir()

    def test_full_dir_valid(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t) / "TX"; d.mkdir()
            self._make(d)
            self.assertEqual(TB.validate_dir(d), [])

    def test_missing_file_and_dir(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t) / "TX"; d.mkdir()
            self._make(d)
            (d / "scoring.md").unlink()
            shutil.rmtree(d / "evidence")
            probs = TB.validate_dir(d)
            self.assertTrue(any("scoring.md" in p for p in probs))
            self.assertTrue(any("evidence/" in p for p in probs))

    def test_task_id_must_match_dirname(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t) / "TX"; d.mkdir()
            self._make(d)
            (d / "meta.json").write_text(json.dumps(_meta(task_id="WRONG")))
            probs = TB.validate_dir(d)
            self.assertTrue(any("!= dir name" in p for p in probs))


class T1Sample(unittest.TestCase):
    def test_t1_dir_is_valid(self):
        self.assertEqual(TB.validate_dir(T1_DIR), [])

    def test_t1_assert_valid_returns_taskspec(self):
        ts = TB.assert_valid(T1_DIR)
        self.assertEqual(ts.task_id, "T1-wechat-send-001")
        self.assertEqual(ts.app, "wechat")

    def test_discover_finds_t1(self):
        self.assertIn("T1-wechat-send-001", TB.discover(ROOT / "tasks"))


if __name__ == "__main__":
    unittest.main()
