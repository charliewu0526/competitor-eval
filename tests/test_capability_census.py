"""功能B: 能力清单差集 (capability_census) 离线单测.

不打网络。用 monkeypatch 替换 capability_store.load_capabilities 注入内存清单:
  (a) 竞品 shipped 有、vio 无 -> diff 列为候选, census 产 capability-gap Finding。
  (b) 竞品能力 vio 已具备(标题/ tag 命中) -> 不列为候选。
  (c) 竞品 limited/marketing/candidate 条目 -> 不当候选(只认 shipped)。
  (d) LLM 抽取: 无论 LLM 标什么, 结果一律降为 candidate(AI 复核闸), 留痕原判。
  (e) review_capability: candidate --approve--> shipped。
"""
from __future__ import annotations
import unittest

from pipeline import capability_store as CS
from pipeline import capability_census as CEN


def _entry(cap, status="shipped", tags=None):
    return CS.CapabilityEntry(capability=cap, status=status,
                              evidence="ev", source="src", tags=tags or [])


class TestCensus(unittest.TestCase):
    def setUp(self):
        self._orig = CS.load_capabilities
        self._lists = {}
        CS.load_capabilities = lambda p: self._lists.get(
            p, CS.CapabilityList(product=p, entries=[]))
        CEN.CS.load_capabilities = CS.load_capabilities

    def tearDown(self):
        CS.load_capabilities = self._orig
        CEN.CS.load_capabilities = self._orig

    def _set(self, product, entries):
        self._lists[product] = CS.CapabilityList(product=product, entries=entries)

    def test_a_rival_only_shipped_is_candidate(self):
        self._set("town", [_entry("专属邮箱入口调用助理"),
                           _entry("预置定时 Routines 晨报")])
        self._set("vio", [_entry("原生本地桌面操控")])
        gaps = CEN.diff_capabilities("town")
        self.assertEqual(len(gaps), 2)
        finds = CEN.census_to_findings("town")
        self.assertEqual(len(finds), 2)
        f = finds[0]
        self.assertEqual(f["suspected_category"], "capability-gap")
        self.assertEqual(f["subject"], "town")
        self.assertEqual(f["rule"], "capability-census")
        # 每条候选独立 task_id: census-<rival>-<能力指纹>(避免多条塌成一条)
        self.assertTrue(f["task_id"].startswith("census-town-"))
        self.assertEqual(len({x["task_id"] for x in finds}), 2)  # 两条候选互不相同
        self.assertTrue(f["evidence"])

    def test_b_vio_already_has_not_candidate(self):
        # vio 已有『定时 Routines』同义能力(标题包含) -> 竞品该条不列候选。
        self._set("town", [_entry("预置定时 Routines")])
        self._set("vio", [_entry("预置定时 Routines 晨报调度")])
        self.assertEqual(CEN.diff_capabilities("town"), [])

    def test_b2_tag_overlap_not_candidate(self):
        self._set("town", [_entry("邮箱多渠道入口", tags=["im-entry"])])
        self._set("vio", [_entry("本地桌面直控微信", tags=["im-entry"])])
        self.assertEqual(CEN.diff_capabilities("town"), [])

    def test_c_only_shipped_counts(self):
        self._set("town", [_entry("有限制的 Outlook 支持", status="limited"),
                           _entry("像皮夹一样贴合你", status="marketing"),
                           _entry("LLM 抽取待复核项", status="candidate")])
        self._set("vio", [])
        self.assertEqual(CEN.diff_capabilities("town"), [])
        self.assertEqual(CEN.census_to_findings("town"), [])

    def test_d_llm_extract_forced_candidate(self):
        from pipeline import gap_attribution as GA
        import os
        os.environ["CLAUDE_API_KEY"] = "test-key"

        class _Resp:
            @staticmethod
            def _fake(*a, **k):
                return {"content": [{"text": '{"entries":[{"capability":"生成演示 deck","status":"shipped","evidence":"官网","source":"docs"}]}'}]}
        orig_post = GA._post_via_proxy
        GA._post_via_proxy = _Resp._fake
        try:
            cl = CEN.extract_capabilities_via_llm("town", "官网原文...", source="docs")
        finally:
            GA._post_via_proxy = orig_post
            del os.environ["CLAUDE_API_KEY"]
        self.assertEqual(len(cl.entries), 1)
        e = cl.entries[0]
        self.assertEqual(e.status, "candidate")          # 强制降级
        self.assertIn("llm:shipped", e.tags)             # 留痕 LLM 原判

    def test_e_review_approve_promotes(self):
        e = CS.CapabilityEntry(capability="c", status="candidate", evidence="ev")
        out = CEN.review_capability(e, approve=True, reviewer="pm1")
        self.assertEqual(out.status, "shipped")
        self.assertIn("reviewed:pm1", out.tags)
        # 非 candidate 不动
        s = CS.CapabilityEntry(capability="c2", status="shipped", evidence="ev")
        self.assertEqual(CEN.review_capability(s, approve=True).status, "shipped")


if __name__ == "__main__":
    unittest.main()
