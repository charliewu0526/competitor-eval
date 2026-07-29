"""E AI 预复核器 precheck 离线单测(mock LLM,不打网络)。

  (a) finding: 合法枚举建议 + 理由。
  (b) finding: 越界枚举 -> None(不塞脏建议)。
  (c) finding: 无 key -> dry_run。
  (d) method: approve / revise 建议;越界 -> None。
  (e) method: 无 key -> dry_run。
"""
from __future__ import annotations
import unittest

from pipeline import precheck as PC


def _patch(monkey):
    PC._call_claude = monkey


class TestPrecheck(unittest.TestCase):
    def setUp(self):
        self._orig = PC._call_claude

    def tearDown(self):
        PC._call_claude = self._orig

    def test_a_finding_valid_suggestion(self):
        _patch(lambda sys, content, **k: {
            "final_category": "feature-gap", "product_judgment": "必须补齐",
            "reason": "竞品有明确能力、vio 缺"})
        r = PC.precheck_finding({"suspected_category": "capability-gap",
                                 "subject": "town", "phenomenon": "p", "evidence": []})
        self.assertEqual(r["suggested_final_category"], "feature-gap")
        self.assertEqual(r["suggested_product_judgment"], "必须补齐")
        self.assertFalse(r["dry_run"])
        self.assertTrue(r["reason"])

    def test_b_finding_out_of_range_none(self):
        _patch(lambda sys, content, **k: {
            "final_category": "乱写的类别", "product_judgment": "瞎判",
            "reason": "x"})
        r = PC.precheck_finding({"phenomenon": "p"})
        self.assertIsNone(r["suggested_final_category"])
        self.assertIsNone(r["suggested_product_judgment"])

    def test_c_finding_dry_run(self):
        _patch(lambda sys, content, **k: {"__dry_run__": True})
        r = PC.precheck_finding({"phenomenon": "p"})
        self.assertTrue(r["dry_run"])
        self.assertIsNone(r["suggested_final_category"])

    def test_d_method_suggestion(self):
        _patch(lambda sys, content, **k: {"suggestion": "approve", "reason": "清晰可执行"})
        r = PC.precheck_method({"task_id": "t", "product": "town", "draft": "## 功能点\nx"})
        self.assertEqual(r["suggestion"], "approve")
        self.assertFalse(r["dry_run"])
        # 越界建议 -> None
        _patch(lambda sys, content, **k: {"suggestion": "maybe", "reason": "x"})
        r2 = PC.precheck_method({"draft": "y"})
        self.assertIsNone(r2["suggestion"])

    def test_e_method_dry_run(self):
        _patch(lambda sys, content, **k: {"__dry_run__": True})
        r = PC.precheck_method({"draft": "y"})
        self.assertTrue(r["dry_run"])
        self.assertIsNone(r["suggestion"])

    def test_f_error_output(self):
        _patch(lambda sys, content, **k: {"error": "unparseable"})
        r = PC.precheck_finding({"phenomenon": "p"})
        self.assertTrue(r["dry_run"])


if __name__ == "__main__":
    unittest.main()
