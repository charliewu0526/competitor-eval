"""C 接线: 矩阵 capability-gap Finding -> 方法卡片 (synthesize_from_matrix) 离线单测.

LLM 提炼 monkeypatch 注入结构化卡片(不打网络):
  (a) 每条 matrix capability-gap Finding -> 一条结构化 draft(product=竞品,标 matrix 来源)。
  (b) 多条候选各得独立 draft(task_id 唯一)。
  (c) 去重幂等。
  (d) 非 capability-gap / 无证据 -> 跳过。
"""
from __future__ import annotations
import tempfile
import unittest

from pipeline import store as STORE
from pipeline import method_synth as MS


def _mfind(task_id, rival="town", ref="[town] 在域X题Y做到了,vio没做到"):
    return {"task_id": task_id, "rule": "capability-matrix",
            "suspected_category": "capability-gap", "subject": rival,
            "phenomenon": "域X横向: town 做到 vio 没做到", "final_category": None,
            "evidence": [{"source": "capability-matrix", "ref": ref}]}


class TestSynthFromMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.con = STORE.connect(self.tmp.name)
        self._orig = MS._synthesize_one
        MS._synthesize_one = lambda p: {"feature_point": "FP", "scope": "SC",
                                        "acceptance": "AC", "rival_practice": "RP",
                                        "suggestion": "SG"}

    def tearDown(self):
        MS._synthesize_one = self._orig
        self.con.close()

    def test_a_each_candidate_one_card(self):
        finds = [_mfind("matrix-ai-aaa"), _mfind("matrix-ai-bbb", rival="manus")]
        created = MS.synthesize_from_matrix(self.con, "assistant-integration", finds)
        self.assertEqual(len(created), 2)
        prods = {m["product"] for m in created}
        self.assertEqual(prods, {"town", "manus"})
        for m in created:
            self.assertIn("capability_matrix", m["draft"])
            self.assertIn("## 功能点", m["draft"])

    def test_b_dedupe(self):
        finds = [_mfind("matrix-ai-aaa")]
        self.assertEqual(len(MS.synthesize_from_matrix(self.con, "ai", finds)), 1)
        self.assertEqual(MS.synthesize_from_matrix(self.con, "ai", finds), [])

    def test_c_skip_non_capgap_or_no_evidence(self):
        bad = dict(_mfind("matrix-ai-ccc"), suspected_category="feature-gap")
        noev = dict(_mfind("matrix-ai-ddd"), evidence=[])
        self.assertEqual(MS.synthesize_from_matrix(self.con, "ai", [bad, noev]), [])

    def test_d_empty(self):
        self.assertEqual(MS.synthesize_from_matrix(self.con, "ai", []), [])


if __name__ == "__main__":
    unittest.main()
