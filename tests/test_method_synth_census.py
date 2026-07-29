"""功能B 接线: census Finding -> 方法初稿 (method_synth.synthesize_from_census) 离线单测.

LLM 提炼 monkeypatch 注入固定功能点(不打网络):
  (a) 每条 capability-gap census Finding -> 一条 draft(product=rival, 标 census 来源)。
  (b) 多条候选各得独立 draft(task_id 唯一, 不塌成一条)。
  (c) 去重幂等: 重跑不重复灌 draft。
  (d) 非 capability-gap / 无证据引用的 finding -> 跳过。
"""
from __future__ import annotations
import tempfile
import unittest

from pipeline import store as STORE
from pipeline import method_synth as MS


def _cap_finding(task_id, ref="[town] 能力X — ev (src)"):
    return {"task_id": task_id, "rule": "capability-census",
            "suspected_category": "capability-gap", "subject": "town",
            "phenomenon": "town 已上线能力X;vio 缺", "final_category": None,
            "product_judgment": None,
            "evidence": [{"source": "capability-list", "ref": ref}]}


class TestSynthFromCensus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.con = STORE.connect(self.tmp.name)
        self._orig = MS._synthesize_one
        MS._synthesize_one = lambda p: {"feature_point": "FP", "suggestion": "SG"}

    def tearDown(self):
        MS._synthesize_one = self._orig
        self.con.close()

    def test_a_each_candidate_one_draft(self):
        finds = [_cap_finding("census-town-aaa", "[town] 邮箱入口 — ev (src)"),
                 _cap_finding("census-town-bbb", "[town] Routines — ev (src)")]
        created = MS.synthesize_from_census(self.con, "town", finds)
        self.assertEqual(len(created), 2)
        for m in created:
            self.assertEqual(m["product"], "town")
            self.assertEqual(m["status"], "draft")
            self.assertIn("capability_census", m["draft"])
            self.assertIn("能力空白", m["draft"])

    def test_b_dedupe_idempotent(self):
        finds = [_cap_finding("census-town-aaa")]
        self.assertEqual(len(MS.synthesize_from_census(self.con, "town", finds)), 1)
        self.assertEqual(MS.synthesize_from_census(self.con, "town", finds), [])

    def test_c_non_capgap_or_no_evidence_skipped(self):
        bad_cat = dict(_cap_finding("census-town-ccc"),
                       suspected_category="feature-gap")
        no_ev = dict(_cap_finding("census-town-ddd"), evidence=[])
        created = MS.synthesize_from_census(self.con, "town", [bad_cat, no_ev])
        self.assertEqual(created, [])

    def test_d_empty(self):
        self.assertEqual(MS.synthesize_from_census(self.con, "town", []), [])


if __name__ == "__main__":
    unittest.main()
