"""差距报告增强: 归因增量预跑 attribution_prefetch 离线单测(mock 归因, 不打网络)。

  (a) 有竞品≥基线且缓存未命中 -> 跑归因落缓存(computed)。
  (b) 无竞品≥基线 -> 写空归因缓存跳过引擎(no_competitor)。
  (c) 重跑(指纹全命中) -> computed=0, cached_hit 覆盖。
  (d) only_tasks 限定只处理指定题。
  (e) 分数变(指纹变) -> 该题重算。
"""
from __future__ import annotations
import tempfile
import unittest

from pipeline import store as STORE
from pipeline import attribution_prefetch as PF
from pipeline import gap_report as GR


def _sc(task, product, score, gate="native-operable"):
    return {"task_id": task, "product": product, "sample_score": score, "gate": gate}


class _FakeReport:
    def __init__(self, task_id):
        self.task_id = task_id

    def as_dict(self):
        return {"attribution": {"task_id": self.task_id, "baseline": "vio",
                                "dry_run": False, "engine": "fake-x",
                                "points": [{"headline": f"{self.task_id} 竞品有联网检索"}]}}


class TestPrefetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.con = STORE.connect(self.tmp.name)
        self._orig_scores = STORE.all_scores
        self._orig_from_store = GR.from_store
        # mock 归因引擎: 直接返回假归因(不读交付物/不调 Claude)
        GR.from_store = lambda con, task_id, baseline="vio", with_attribution=False, **k: _FakeReport(task_id)
        # mock 方法提炼: 默认 also_synthesize=True 会调它, 挡住不真调 LLM;
        # 记录被提炼的 task_id 供断言。
        from pipeline import method_synth as MSYN
        self._orig_synth = MSYN.synthesize_from_attribution
        self.synth_calls = []

        def _fake_synth(con, task_id, attr, **k):
            self.synth_calls.append(task_id)
            return [{"id": 1, "task_id": task_id}]   # 假装落了一条 draft
        MSYN.synthesize_from_attribution = _fake_synth
        self._MSYN = MSYN

    def tearDown(self):
        STORE.all_scores = self._orig_scores
        GR.from_store = self._orig_from_store
        self._MSYN.synthesize_from_attribution = self._orig_synth
        self.con.close()

    def _set_scores(self, rows):
        STORE.all_scores = lambda con: rows

    def test_g_auto_synthesize_closes_loop(self):
        # 有实质归因点 -> 默认 also_synthesize=True 自动提炼方法初稿(闭环)。
        self._set_scores([_sc("T1", "vio", 0.5), _sc("T1", "town", 0.9)])
        st = PF.prefetch(self.con, "vio")
        self.assertEqual(st["synthesized"], 1)
        self.assertIn("T1", self.synth_calls)

    def test_h_no_synthesize_when_disabled(self):
        self._set_scores([_sc("T1", "vio", 0.5), _sc("T1", "town", 0.9)])
        st = PF.prefetch(self.con, "vio", also_synthesize=False)
        self.assertEqual(st.get("synthesized", 0), 0)
        self.assertEqual(self.synth_calls, [])

    def test_i_no_competitor_not_synthesized(self):
        # 无竞品(空归因)不提炼。
        self._set_scores([_sc("T1", "vio", 0.9), _sc("T1", "town", 0.1)])
        PF.prefetch(self.con, "vio")
        self.assertEqual(self.synth_calls, [])

    def test_a_competitor_computes(self):
        self._set_scores([_sc("T1", "vio", 0.5), _sc("T1", "town", 0.9)])
        st = PF.prefetch(self.con, "vio")
        self.assertEqual(st["computed"], 1)
        fp = STORE.attribution_fingerprint([_sc("T1", "vio", 0.5), _sc("T1", "town", 0.9)])
        hit = STORE.get_cached_attribution(self.con, "T1", "vio", fp)
        self.assertIsNotNone(hit)
        self.assertIn("联网检索", hit["points"][0]["headline"])

    def test_b_no_competitor_skips_engine(self):
        # vio 领先, 无竞品≥基线 -> 写空归因, no_competitor
        self._set_scores([_sc("T1", "vio", 0.9), _sc("T1", "town", 0.1)])
        st = PF.prefetch(self.con, "vio")
        self.assertEqual(st["no_competitor"], 1)
        self.assertEqual(st["computed"], 0)
        fp = STORE.attribution_fingerprint([_sc("T1", "vio", 0.9), _sc("T1", "town", 0.1)])
        hit = STORE.get_cached_attribution(self.con, "T1", "vio", fp)
        self.assertEqual(hit["points"], [])
        self.assertIn("无需归因", hit["note"])

    def test_c_rerun_all_cached(self):
        self._set_scores([_sc("T1", "vio", 0.5), _sc("T1", "town", 0.9)])
        PF.prefetch(self.con, "vio")
        st2 = PF.prefetch(self.con, "vio")   # 重跑
        self.assertEqual(st2["computed"], 0)
        self.assertEqual(st2["cached_hit"], 1)

    def test_d_only_tasks(self):
        self._set_scores([_sc("T1", "vio", 0.5), _sc("T1", "town", 0.9),
                          _sc("T2", "vio", 0.5), _sc("T2", "town", 0.9)])
        st = PF.prefetch(self.con, "vio", only_tasks=["T2"])
        self.assertEqual(st["scanned"], 1)
        self.assertEqual(st["computed"], 1)

    def test_e_score_change_recomputes(self):
        self._set_scores([_sc("T1", "vio", 0.5), _sc("T1", "town", 0.9)])
        PF.prefetch(self.con, "vio")
        # 分数变 -> 指纹变 -> 缓存失效 -> 重算
        self._set_scores([_sc("T1", "vio", 0.7), _sc("T1", "town", 0.9)])
        st = PF.prefetch(self.con, "vio")
        self.assertEqual(st["computed"], 1)
        self.assertEqual(st["cached_hit"], 0)

    def test_f_force_recompute(self):
        self._set_scores([_sc("T1", "vio", 0.5), _sc("T1", "town", 0.9)])
        PF.prefetch(self.con, "vio")
        st = PF.prefetch(self.con, "vio", force=True)
        self.assertEqual(st["computed"], 1)   # force 忽略缓存


if __name__ == "__main__":
    unittest.main()
