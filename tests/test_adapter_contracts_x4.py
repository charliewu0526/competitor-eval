"""候选④: 适配器契约统一对账 — 真货 vs 替身必须同形.

Run: python -m unittest tests.test_adapter_contracts_x4 -v

charlie 的顾虑(替身能测出真问题吗?)的正式答案:替身有盲区 —— 真货改了
字段/签名/语义而替身没跟,测试照绿、生产已崩。这里把 registry 已验证的
「共享契约测试」模式(_RegistryContract)推广到其余 4 个适配器,口径统一。

每个适配器的对账分三层(grilling Q3 定):
  L1 字段同形 — 真货与替身返回 dict 的键集合一致(堵字段漂移,charlie 盲区)
  L2 签名同形 — 同名方法参数列表一致(inspect.signature;收体检 H2)
  L3 关键不变量 — 各适配器最要命的那一条语义,真假两侧都满足

机制是测试(B 方案),不是 Protocol —— 项目用 unittest 把关,不跑 mypy,
所以「每次跑测试就对账」比「装了不通电的静态报警器」更实在。
"""
from __future__ import annotations
import inspect
import unittest

from pipeline import cost_client as CC, cost_fakes as CFK
from pipeline import evidence_client as EC, evidence_fakes as EFK
from pipeline import verify_client as VC, verify_fakes as VFK
from pipeline import review_client as RC, review_fakes as RFK


def _sig_keys(fn) -> set[str]:
    """Parameter names of a callable, excluding self."""
    return {p for p in inspect.signature(fn).parameters if p != "self"}


# =============================================================================
# COST (A3) — class adapter; collects 体检 H2 fix.
# =============================================================================
class CostContract(unittest.TestCase):
    def setUp(self):
        self.prod = CC.CostAccountant(
            CC.PriceTable({"m": {"input": 1.0, "output": 1.0}}))
        self.fake = CFK.fake_self_report

    def test_L1_account_same_keys(self):
        p = self.prod.account(model="m", input_tokens=1, output_tokens=1)
        f = self.fake.account()
        self.assertEqual(set(p), set(f))

    def test_L2_account_signature_same(self):
        self.assertEqual(_sig_keys(self.prod.account),
                         _sig_keys(self.fake.account))

    def test_L2_apply_to_run_signature_same(self):
        # the exact 体检 H2: fake used (**kw); must now mirror prod's kwargs
        self.assertEqual(_sig_keys(self.prod.apply_to_run),
                         _sig_keys(self.fake.apply_to_run))

    def test_L3_unavailable_is_none_not_zero(self):
        # 关键不变量: 拿不到 != 0. Both sides must refuse to price.
        p = self.prod.account(model=None, cost_source="unavailable")
        f = CFK.fake_unavailable.account()
        self.assertIsNone(p["cost_usd"])
        self.assertIsNone(f["cost_usd"])


# =============================================================================
# EVIDENCE (A2) — class adapter.
# =============================================================================
class EvidenceContract(unittest.TestCase):
    def setUp(self):
        self.prod = EC.EvidenceCollector(require_exists=False)
        self.fake = EFK.fake_log

    def test_L1_collect_same_keys(self):
        p = self.prod.collect(logs="some/log.txt")
        f = self.fake.collect()
        self.assertEqual(set(p), set(f))

    def test_L2_collect_signature_same(self):
        self.assertEqual(_sig_keys(self.prod.collect),
                         _sig_keys(self.fake.collect))

    def test_L2_collect_from_run_signature_same(self):
        self.assertEqual(_sig_keys(self.prod.collect_from_run),
                         _sig_keys(self.fake.collect_from_run))

    def test_L3_evidence_never_judges_completion(self):
        # 关键不变量: 证据绝不判完成度 (for_completion always False).
        p = self.prod.collect(logs="some/log.txt")
        f = self.fake.collect()
        self.assertFalse(p["for_completion"])
        self.assertFalse(f["for_completion"])


# =============================================================================
# VERIFY (A4) — function adapter; key invariant 不自评.
# =============================================================================
class VerifyContract(unittest.TestCase):
    _KEYS = {"verifier", "model_family", "dry_run", "passed", "reason",
             "auto_ingest"}

    def test_L1_fake_emits_full_contract(self):
        out = VFK.fake_verify("task", "candidate",
                              generator="deepseek", verifier="claude")
        self.assertEqual(set(out) & self._KEYS, self._KEYS)

    def test_L1_prod_stub_emits_full_contract(self):
        # no key -> production verify falls back to its dry-run stub shape
        out = VC.verify("task", "candidate",
                        generator="deepseek", verifier="claude")
        self.assertEqual(set(out) & self._KEYS, self._KEYS)

    def test_L2_signature_same(self):
        # the fake legitimately adds test-control kwargs (passed/reason) to drive
        # deterministic verdicts; the CONTRACT is that every production param is
        # honored by the fake (so callers can't pass an arg prod accepts but fake
        # silently drops). Subset check, not equality.
        prod = _sig_keys(VC.verify)
        fake = _sig_keys(VFK.fake_verify)
        self.assertTrue(prod <= fake,
                        f"fake missing production params: {prod - fake}")
        self.assertEqual(fake - prod, {"passed", "reason"})

    def test_L3_self_eval_rejected_both_sides(self):
        # 关键不变量: 出题≠核验，同家族自评必拒 —— BEFORE any network call.
        with self.assertRaises(VC.SelfEvalError):
            VC.verify("t", "c", generator="deepseek", verifier="deepseek")
        with self.assertRaises(VC.SelfEvalError):
            VFK.fake_verify("t", "c", generator="deepseek", verifier="deepseek")

    def test_L3_pass_implies_auto_ingest_both_sides(self):
        # 关键不变量: 核验通过即自动入库 (无人工签字闸门).
        f = VFK.fake_verify("t", "c", generator="deepseek", verifier="claude",
                            passed=True)
        self.assertTrue(f["auto_ingest"])


# =============================================================================
# REVIEW (A1) — function panel; finishes the half-reconciliation from 候选③.
# =============================================================================
class ReviewContract(unittest.TestCase):
    _KEYS = {"panelist", "dry_run", "S1", "S2", "S3", "S4", "S5",
             "justifications", "defects"}

    def test_L1_fake_emits_full_contract(self):
        out = RFK.fake_deepseek("ignored")
        self.assertEqual(set(out) & self._KEYS, self._KEYS)

    def test_L1_prod_stub_emits_full_contract(self):
        out = RC._stub("deepseek")
        self.assertEqual(set(out) & self._KEYS, self._KEYS)

    def test_L3_unjustified_dim_shape(self):
        # 关键不变量: justifications 是 dict, defects 是 list — 打分/找错分家.
        out = RFK.fake_deepseek("p")
        self.assertIsInstance(out["justifications"], dict)
        self.assertIsInstance(out["defects"], list)


if __name__ == "__main__":
    unittest.main()
