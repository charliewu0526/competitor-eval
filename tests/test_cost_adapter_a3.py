"""A3 (#21): cost-accounting adapter + 单价表.

Run: python -m unittest tests.test_cost_adapter_a3 -v

Acceptance (issue #21), all OFFLINE:
  - production: collect token/calls, fold cost_usd via 单价表, stamp cost_source
  - in-memory fake: returns a fixed cost triple + source
  - both impls satisfy the SAME contract
  - 单价表 independent file; 改价不改代码; 缺价 -> cost_usd unavailable (None)
  - 成本与 sample_score 并排可取 (cost never read alone)
"""
from __future__ import annotations
import json
import pathlib
import tempfile
import unittest

from pipeline import cost_client as CC
from pipeline import cost_fakes as CF
from pipeline import store
from pipeline.schema import RunRecord, TaskSpec, COST_SOURCE_VALUES

CONTRACT_KEYS = {"cost_input_tokens", "cost_output_tokens", "cost_model_calls",
                 "cost_usd", "cost_source", "priced", "model",
                 "price_table_updated"}


def _table(**models):
    return CC.PriceTable({"currency": "USD", "unit": "per_million_tokens",
                          "updated": "test", "models": models})


# =============================================================================
# Price table: independent file, fold tokens -> $, 缺价 -> None.
# =============================================================================
class PriceTableTests(unittest.TestCase):
    def test_default_table_loads_from_json_file(self):
        pt = CC.PriceTable.load()
        self.assertTrue(pt.has("deepseek-v4-pro"))
        self.assertEqual(pt.unit, "per_million_tokens")

    def test_fold_tokens_to_usd(self):
        pt = _table(m={"input": 1.0, "output": 2.0})  # $/1M
        # 1M input @ $1 + 0.5M output @ $2 = 1 + 1 = $2
        self.assertEqual(pt.cost_usd("m", 1_000_000, 500_000), 2.0)

    def test_missing_price_is_none_not_zero(self):
        pt = _table(m={"input": 1.0, "output": 2.0})
        self.assertIsNone(pt.cost_usd("unknown-model", 1000, 1000))

    def test_change_price_without_touching_code(self):
        # Writing a new JSON file changes the $ — no code edit.
        d = tempfile.mkdtemp()
        p = pathlib.Path(d) / "prices.json"
        p.write_text(json.dumps({"models": {"m": {"input": 10.0, "output": 10.0}}}))
        pt = CC.PriceTable.load(p)
        self.assertEqual(pt.cost_usd("m", 1_000_000, 0), 10.0)


# =============================================================================
# Production accountant: three numbers + honest source.
# =============================================================================
class ProductionAccountant(unittest.TestCase):
    def setUp(self):
        self.acc = CC.CostAccountant(_table(
            **{"deepseek-v4-pro": {"input": 0.27, "output": 1.10}}))

    def test_records_three_numbers_and_prices(self):
        out = self.acc.account(model="deepseek-v4-pro",
                               input_tokens=2_000_000, output_tokens=1_000_000,
                               model_calls=7, cost_source="self-report")
        self.assertEqual(out["cost_input_tokens"], 2_000_000)
        self.assertEqual(out["cost_output_tokens"], 1_000_000)
        self.assertEqual(out["cost_model_calls"], 7)
        # 2*0.27 + 1*1.10 = 1.64
        self.assertEqual(out["cost_usd"], 1.64)
        self.assertEqual(out["cost_source"], "self-report")
        self.assertTrue(out["priced"])

    def test_unavailable_never_prices_a_zero(self):
        out = self.acc.account(model="deepseek-v4-pro", input_tokens=999,
                               output_tokens=999, model_calls=3,
                               cost_source="unavailable")
        self.assertIsNone(out["cost_usd"])
        self.assertFalse(out["priced"])
        self.assertEqual(out["cost_source"], "unavailable")
        # tokens still recorded honestly
        self.assertEqual(out["cost_input_tokens"], 999)

    def test_missing_price_unavailable_usd_but_keeps_source(self):
        out = self.acc.account(model="some-uncharted-model",
                               input_tokens=1000, output_tokens=1000,
                               cost_source="self-report")
        self.assertIsNone(out["cost_usd"])      # 缺价 -> None
        self.assertFalse(out["priced"])
        self.assertEqual(out["cost_source"], "self-report")  # source unaffected

    def test_proxy_source_prices_normally(self):
        out = self.acc.account(model="deepseek-v4-pro", input_tokens=1_000_000,
                               output_tokens=0, cost_source="proxy")
        self.assertEqual(out["cost_usd"], 0.27)
        self.assertEqual(out["cost_source"], "proxy")

    def test_bad_source_rejected(self):
        with self.assertRaises(ValueError):
            self.acc.account(model="deepseek-v4-pro", cost_source="made-up")

    def test_apply_to_run_writes_back_fields(self):
        rr = RunRecord(task_id="T1", product="vio", run_idx=1,
                       gate="native-operable")
        out = self.acc.apply_to_run(rr, model="deepseek-v4-pro",
                                    input_tokens=1_000_000, output_tokens=0,
                                    model_calls=4, cost_source="self-report")
        self.assertEqual(rr.cost_usd, 0.27)
        self.assertEqual(rr.cost_model_calls, 4)
        self.assertEqual(rr.cost_source, "self-report")
        self.assertEqual(out["cost_usd"], rr.cost_usd)


# =============================================================================
# In-memory fake: fixed triple + same contract.
# =============================================================================
class FakeContract(unittest.TestCase):
    def test_fake_returns_fixed_triple(self):
        out = CF.fake_self_report.account()
        self.assertEqual(out["cost_input_tokens"], 1000)
        self.assertEqual(out["cost_usd"], 0.001)
        self.assertTrue(out["priced"])
        self.assertEqual(out["cost_source"], "self-report")

    def test_fake_unavailable_has_no_usd(self):
        out = CF.fake_unavailable.account()
        self.assertIsNone(out["cost_usd"])
        self.assertFalse(out["priced"])
        self.assertEqual(out["cost_source"], "unavailable")

    def test_fake_is_deterministic(self):
        self.assertEqual(CF.fake_proxy.account(), CF.fake_proxy.account())

    def test_both_impls_same_contract_keys(self):
        acc = CC.CostAccountant(_table(m={"input": 1.0, "output": 1.0}))
        prod = acc.account(model="m", input_tokens=1, output_tokens=1)
        fake = CF.fake_self_report.account()
        self.assertEqual(set(prod), CONTRACT_KEYS)
        self.assertEqual(set(fake), CONTRACT_KEYS)

    def test_fake_source_values_valid(self):
        for f in CF.FAKE_ACCOUNTANTS.values():
            self.assertIn(f.account()["cost_source"], COST_SOURCE_VALUES)


# =============================================================================
# 成本与 sample_score 并排可取 (cost never read alone).
# =============================================================================
class CostWithCompletion(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(":memory:")

    def _seed(self, *, product, in_tok, out_tok, calls, usd, source,
              sample_score, failed_primary, objective_ratio):
        rr = RunRecord(task_id="T1", product=product, run_idx=1,
                       gate="native-operable",
                       objective_failed_primary=failed_primary,
                       cost_input_tokens=in_tok, cost_output_tokens=out_tok,
                       cost_model_calls=calls, cost_usd=usd, cost_source=source)
        store.upsert_run(self.con, rr)
        store.upsert_score(self.con, {
            "task_id": "T1", "product": product, "run_idx": 1,
            "gate": "native-operable", "scored": True,
            "objective_ratio": objective_ratio, "sample_score": sample_score,
            "objective_failed_primary": failed_primary,
        })

    def test_cost_joins_to_completion(self):
        # cheap+done vs cheap-but-didn't-finish (the摆烂 trap)
        self._seed(product="vio", in_tok=1000, out_tok=500, calls=3,
                   usd=0.01, source="self-report", sample_score=0.9,
                   failed_primary=False, objective_ratio=1.0)
        self._seed(product="rival", in_tok=200, out_tok=50, calls=1,
                   usd=0.002, source="self-report", sample_score=0.0,
                   failed_primary=True, objective_ratio=0.0)
        rows = {r["product"]: r for r in store.cost_with_completion(self.con)}
        # both expose cost AND sample_score in the same row
        self.assertEqual(rows["vio"]["cost_usd"], 0.01)
        self.assertEqual(rows["vio"]["sample_score"], 0.9)
        # rival looks 'cheaper' but failed primary => not a win
        self.assertLess(rows["rival"]["cost_usd"], rows["vio"]["cost_usd"])
        self.assertEqual(rows["rival"]["sample_score"], 0.0)
        self.assertTrue(rows["rival"]["objective_failed_primary"])

    def test_unavailable_cost_row_is_visible_not_zero(self):
        self._seed(product="cloudbox", in_tok=0, out_tok=0, calls=0,
                   usd=None, source="unavailable", sample_score=0.7,
                   failed_primary=False, objective_ratio=1.0)
        row = store.cost_with_completion(self.con)[0]
        self.assertIsNone(row["cost_usd"])
        self.assertFalse(row["cost_priced"])
        self.assertEqual(row["cost_source"], "unavailable")
        self.assertEqual(row["sample_score"], 0.7)   # completion still readable


if __name__ == "__main__":
    unittest.main()
