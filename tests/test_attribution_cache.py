"""差距报告增强: 归因缓存 + scores 指纹 store 层离线单测。

  (a) 指纹: 同输入稳定; 分数变/产品增删/gate变 -> 指纹变。
  (b) 缓存: 写入后同指纹命中(带 cached 标); 指纹不符返回 None(失效)。
  (c) all_cached_attributions 批量读带出指纹+时间。
"""
from __future__ import annotations
import tempfile
import unittest

from pipeline import store as STORE


def _sc(product, score, gate="native-operable"):
    return {"task_id": "T1", "product": product, "sample_score": score, "gate": gate}


class TestAttributionCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.con = STORE.connect(self.tmp.name)

    def tearDown(self):
        self.con.close()

    def test_a_fingerprint_stable_and_sensitive(self):
        s1 = [_sc("vio", 0.5), _sc("town", 0.9)]
        s2 = [_sc("town", 0.9), _sc("vio", 0.5)]   # 顺序无关
        self.assertEqual(STORE.attribution_fingerprint(s1),
                         STORE.attribution_fingerprint(s2))
        # 分数变 -> 指纹变
        s3 = [_sc("vio", 0.6), _sc("town", 0.9)]
        self.assertNotEqual(STORE.attribution_fingerprint(s1),
                            STORE.attribution_fingerprint(s3))
        # 增产品 -> 指纹变
        s4 = s1 + [_sc("manus", 0.4)]
        self.assertNotEqual(STORE.attribution_fingerprint(s1),
                            STORE.attribution_fingerprint(s4))
        # gate 变 -> 指纹变
        s5 = [_sc("vio", 0.5), _sc("town", 0.9, gate="cannot-reach")]
        self.assertNotEqual(STORE.attribution_fingerprint(s1),
                            STORE.attribution_fingerprint(s5))
        # baseline 不同 -> 指纹变
        self.assertNotEqual(STORE.attribution_fingerprint(s1, "vio"),
                            STORE.attribution_fingerprint(s1, "claude"))

    def test_b_cache_hit_and_stale(self):
        fp = STORE.attribution_fingerprint([_sc("vio", 0.5), _sc("town", 0.9)])
        STORE.upsert_attribution_cache(
            self.con, task_id="T1", baseline="vio", scores_fingerprint=fp,
            attribution={"points": [{"headline": "town 有联网检索"}]}, engine="claude-x")
        # 同指纹命中
        hit = STORE.get_cached_attribution(self.con, "T1", "vio", fp)
        self.assertIsNotNone(hit)
        self.assertTrue(hit["cached"])
        self.assertEqual(hit["points"][0]["headline"], "town 有联网检索")
        # 指纹不符 -> None(失效)
        self.assertIsNone(STORE.get_cached_attribution(self.con, "T1", "vio", "OTHER"))
        # 不存在的题 -> None
        self.assertIsNone(STORE.get_cached_attribution(self.con, "T9", "vio", fp))

    def test_c_upsert_overwrites(self):
        STORE.upsert_attribution_cache(self.con, task_id="T1", baseline="vio",
                                       scores_fingerprint="fp1", attribution={"v": 1})
        STORE.upsert_attribution_cache(self.con, task_id="T1", baseline="vio",
                                       scores_fingerprint="fp2", attribution={"v": 2})
        # 只剩最新一行
        got = STORE.get_cached_attribution(self.con, "T1", "vio", "fp2")
        self.assertEqual(got["v"], 2)
        self.assertIsNone(STORE.get_cached_attribution(self.con, "T1", "vio", "fp1"))

    def test_d_all_cached(self):
        STORE.upsert_attribution_cache(self.con, task_id="T1", baseline="vio",
                                       scores_fingerprint="fpA", attribution={"points": []})
        STORE.upsert_attribution_cache(self.con, task_id="T2", baseline="vio",
                                       scores_fingerprint="fpB", attribution={"points": []})
        allc = STORE.all_cached_attributions(self.con, "vio")
        self.assertEqual(set(allc), {"T1", "T2"})
        self.assertEqual(allc["T1"]["scores_fingerprint"], "fpA")


if __name__ == "__main__":
    unittest.main()
