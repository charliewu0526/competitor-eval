"""E 一致率记录 store 层单测(precheck_log)。

  (a) 记 AI 建议 -> 人一致 -> agreed=1。
  (b) 记 AI 建议 -> 人不一致 -> agreed=0。
  (c) precheck_agreement 汇总(总/按 target_type)算对。
  (d) 无未决建议 -> record 返回 False(不硬造)。
  (e) get_precheck_suggestion 取最新一条(解析 suggestion_json)。
  (f) 幂等: 同目标重复 log 未决建议只留最新一条。
"""
from __future__ import annotations
import tempfile
import unittest

from pipeline import store as STORE


class TestPrecheckLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.con = STORE.connect(self.tmp.name)

    def tearDown(self):
        self.con.close()

    def _log(self, tid, sug):
        STORE.log_precheck_suggestion(self.con, target_type="finding",
                                      target_id=tid, suggestion=sug)

    def test_a_b_c_agreement(self):
        self._log("1", {"suggested_final_category": "feature-gap", "reason": "r"})
        STORE.record_precheck_decision(self.con, target_type="finding", target_id="1",
                                       human_decision="feature-gap",
                                       suggested_value="feature-gap", reviewer="pm")
        self._log("2", {"suggested_final_category": "bug", "reason": "r"})
        STORE.record_precheck_decision(self.con, target_type="finding", target_id="2",
                                       human_decision="feature-gap",
                                       suggested_value="bug", reviewer="pm")
        STORE.log_precheck_suggestion(self.con, target_type="method", target_id="9",
                                      suggestion={"suggestion": "approve"})
        STORE.record_precheck_decision(self.con, target_type="method", target_id="9",
                                       human_decision="approve",
                                       suggested_value="approve", reviewer="pm")
        agr = STORE.precheck_agreement(self.con)
        self.assertEqual((agr["decided"], agr["agreed"]), (3, 2))
        agrf = STORE.precheck_agreement(self.con, target_type="finding")
        self.assertEqual((agrf["decided"], agrf["agreed"]), (2, 1))

    def test_d_no_open_suggestion(self):
        self.assertFalse(STORE.record_precheck_decision(
            self.con, target_type="finding", target_id="99",
            human_decision="bug", suggested_value="bug"))

    def test_e_get_latest(self):
        self._log("5", {"suggested_final_category": "bug", "reason": "r1"})
        g = STORE.get_precheck_suggestion(self.con, "finding", "5")
        self.assertEqual(g["suggestion"]["suggested_final_category"], "bug")
        self.assertIsNone(g["agreed"])

    def test_f_idempotent_open(self):
        self._log("7", {"suggested_final_category": "bug"})
        self._log("7", {"suggested_final_category": "feature-gap"})
        rows = list(self.con.execute(
            "SELECT * FROM precheck_log WHERE target_id='7' AND agreed IS NULL"))
        self.assertEqual(len(rows), 1)   # 只留最新未决


if __name__ == "__main__":
    unittest.main()
