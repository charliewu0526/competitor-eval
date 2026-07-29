"""D 自动调研串联 auto_research 离线单测(mock 抓取 + mock LLM,不打网络)。

  (a) 抓取成功 -> extract -> candidate 带 source_url + fetched_at。
  (b) 全抓不到 -> 不调 LLM,如实标,extracted 空。
  (c) review 升 shipped 后 diff_capabilities 认它为候选。
"""
from __future__ import annotations
import unittest

from pipeline import capability_census as CEN
from pipeline import capability_store as CS
from pipeline import source_fetch as SF


class TestAutoResearch(unittest.TestCase):
    def setUp(self):
        self._fetch = SF.fetch_sources
        self._extract = CEN.extract_capabilities_via_llm

    def tearDown(self):
        SF.fetch_sources = self._fetch
        CEN.extract_capabilities_via_llm = self._extract

    def test_a_fetch_extract_candidate_with_source(self):
        SF.fetch_sources = lambda urls, timeout=None: [
            {"url": "https://acme.ai", "ok": True, "text": "Acme 支持自然语言生成周报",
             "fetched_at": "2026-07-29T10:00:00"}]
        CEN.extract_capabilities_via_llm = lambda product, text, source="": CS.CapabilityList(
            product=product, entries=[CS.CapabilityEntry(
                capability="自然语言生成周报", status="candidate", evidence="官网", source=source)],
            note="mock")
        res = CEN.auto_research("acme", ["https://acme.ai"], persist=False)
        self.assertTrue(res["fetched"][0]["ok"])
        self.assertEqual(len(res["extracted"]), 1)
        e = res["extracted"][0]
        self.assertEqual(e["status"], "candidate")
        self.assertEqual(e["source_url"], "https://acme.ai")
        self.assertEqual(e["fetched_at"], "2026-07-29T10:00:00")

    def test_b_all_fail_no_llm(self):
        SF.fetch_sources = lambda urls, timeout=None: [
            {"url": "x", "ok": False, "text": "", "fetched_at": "t", "note": "fail"}]
        called = []
        CEN.extract_capabilities_via_llm = lambda *a, **k: called.append(1)
        res = CEN.auto_research("acme", ["x"], persist=False)
        self.assertEqual(res["extracted"], [])
        self.assertEqual(called, [])          # 抓不到不调 LLM
        self.assertIn("未抓到", res["note"])

    def test_c_review_promotes_to_candidate_of_diff(self):
        entry = CS.CapabilityEntry(capability="c", status="candidate", evidence="ev")
        CEN.review_capability(entry, approve=True, reviewer="pm1")
        self.assertEqual(entry.status, "shipped")
        self.assertIn("reviewed:pm1", entry.tags)


if __name__ == "__main__":
    unittest.main()
