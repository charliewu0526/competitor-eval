"""C 多竞品能力域矩阵: 分类 + gap/lead + 单次失败守卫 离线单测.

不打网络。task_domain 用 monkeypatch 注入内存域映射(不读 meta.json)。
  (a) 分类: did / did-not / cannot-reach / no-data。
  (b) 竞品做到、vio 没做到 -> gap 候选; matrix_to_capability_gap_findings 产 capability-gap。
  (c) 单次失败守卫: vio 在同域他题具备该能力 -> 该题不判空白。
  (d) vio 做到、竞品普遍没做到 -> lead(对称呈现)。
  (e) cannot-reach 不算失败,不进 gap。
"""
from __future__ import annotations
import unittest

from pipeline import capability_matrix as CM


def _sc(task, product, score=None, gate="native-operable", failed=False, scored=True):
    return {"task_id": task, "product": product, "sample_score": score,
            "gate": gate, "objective_failed_primary": failed, "scored": scored}


class TestCapabilityMatrix(unittest.TestCase):
    def setUp(self):
        self._orig = CM.task_domain
        # 全部题归到 assistant-integration 域(测试内)
        CM.task_domain = lambda t: "assistant-integration"

    def tearDown(self):
        CM.task_domain = self._orig

    def test_a_classify(self):
        self.assertEqual(CM._classify(None), CM.NO_DATA)
        self.assertEqual(CM._classify(_sc("t", "p", score=0.8)), CM.DID)
        self.assertEqual(CM._classify(_sc("t", "p", score=0.0)), CM.DID_NOT)
        self.assertEqual(CM._classify(_sc("t", "p", failed=True)), CM.DID_NOT)
        self.assertEqual(CM._classify(_sc("t", "p", gate="cannot-reach")), CM.NOT_REACH)

    def test_b_rival_did_vio_not_makes_gap(self):
        scores = [
            _sc("TA2", "vio", score=0.0, failed=True),   # vio 这题失败
            _sc("TA2", "town", score=0.9),               # town 做到
            # vio 在同域没有别的成功题 -> 不触发守卫
        ]
        m = CM.build_matrix(scores, "assistant-integration")
        self.assertEqual(len(m.gaps), 1)
        self.assertEqual(m.gaps[0]["rival"], "town")
        finds = CM.matrix_to_capability_gap_findings(m)
        self.assertEqual(len(finds), 1)
        f = finds[0]
        self.assertEqual(f["suspected_category"], "capability-gap")
        self.assertEqual(f["subject"], "town")
        self.assertEqual(f["rule"], "capability-matrix")
        self.assertTrue(f["task_id"].startswith("matrix-assistant-integration-"))

    def test_c_single_failure_guard(self):
        # vio 这题失败, 但同域另一题成功 -> 视为偶发失败, 不判空白。
        scores = [
            _sc("TA2", "vio", score=0.0, failed=True),
            _sc("TA2", "town", score=0.9),
            _sc("TA3", "vio", score=0.85),               # vio 同域他题做到了
        ]
        m = CM.build_matrix(scores, "assistant-integration")
        self.assertEqual(m.gaps, [])                     # 守卫生效

    def test_d_vio_did_rivals_not_makes_lead(self):
        scores = [
            _sc("TA3", "vio", score=0.85),
            _sc("TA3", "town", score=0.0, failed=True),
        ]
        m = CM.build_matrix(scores, "assistant-integration")
        self.assertEqual(len(m.leads), 1)
        self.assertEqual(m.leads[0]["task_id"], "TA3")

    def test_e_cannot_reach_not_gap(self):
        # town cannot-reach(没参赛)-> 不算它做到, vio 失败也不因它产 gap。
        scores = [
            _sc("TA2", "vio", score=0.0, failed=True),
            _sc("TA2", "town", gate="cannot-reach"),
        ]
        m = CM.build_matrix(scores, "assistant-integration")
        self.assertEqual(m.gaps, [])

    def test_f_unique_task_ids(self):
        scores = [
            _sc("TA2", "vio", score=0.0, failed=True), _sc("TA2", "town", score=0.9),
            _sc("TA4", "vio", score=0.0, failed=True), _sc("TA4", "manus", score=0.8),
        ]
        m = CM.build_matrix(scores, "assistant-integration")
        finds = CM.matrix_to_capability_gap_findings(m)
        tids = [f["task_id"] for f in finds]
        self.assertEqual(len(tids), len(set(tids)))      # 各候选独立 task_id


if __name__ == "__main__":
    unittest.main()
