"""F1: TaskSpec / RunRecord v2 schema tests. Stdlib unittest (no pytest dep).

Run: python -m unittest tests.test_schema_v2 -v
Covers acceptance: enum rejection, heavy=>known_edge_cases, back-compat load.
"""
from __future__ import annotations
import json, tempfile, unittest, pathlib
from dataclasses import fields as dc_fields
from pipeline.schema import TaskSpec, RunRecord, save, load_json
from pipeline import store as STORE


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


class SchemaStoreConsistency(unittest.TestCase):
    """候选⑤: 一致性守护 — RunRecord 字段 ↔ runs 表列, 出事前提醒.

    RunRecord 的字段定义在三处:数据类(schema)、手写建表 SQL(store)、
    taskbank 校验(已从数据类派生)。建表 SQL 是手抄的,加字段忘改它会静默丢
    数据(A3 cost_* 列曾被咬过)。_migrate() 在运行时兜底补列;这道测试在
    测试期就报警:数据类新增一个【该入库】的标量字段而 SQL 没跟 -> 当场红。

    部分字段【故意不入 runs 表】(列表/dict 不落标量列),列在豁免名单里 ——
    名单本身就是「为什么这字段不入库」的活文档;新加的豁免必须显式登记。
    """

    # RunRecord scalar fields that are deliberately NOT persisted as runs columns.
    _NOT_PERSISTED = {
        "artifact_path",   # path ref, kept in JSON artifacts, not a ranked column
        "screenshots",     # list -> not a scalar column
        "env_meta",        # dict -> not a scalar column
    }

    def _runs_columns(self):
        con = STORE.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")
        return {r[1] for r in con.execute("PRAGMA table_info(runs)")}

    def test_every_persistable_field_has_a_column(self):
        cols = self._runs_columns()
        record_fields = {f.name for f in dc_fields(RunRecord)}
        should_persist = record_fields - self._NOT_PERSISTED
        missing = should_persist - cols
        self.assertEqual(missing, set(),
                         f"RunRecord 字段没有对应 runs 列(加字段忘改建表 SQL?): "
                         f"{missing}")

    def test_exemptions_are_real_fields(self):
        # guard the guard: an exemption must name a real field, else it's stale.
        record_fields = {f.name for f in dc_fields(RunRecord)}
        stale = self._NOT_PERSISTED - record_fields
        self.assertEqual(stale, set(),
                         f"豁免名单里有不存在的字段(已删除?请清理): {stale}")


if __name__ == "__main__":
    unittest.main()
