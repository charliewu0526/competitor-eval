"""归因 -> 一句话功能点 -> 自动方法初稿 (method_synth) 离线单测.

只测**不打网络**的自动流转逻辑, LLM 调用用 monkeypatch 注入假提炼:
  (a) 有原文引用的归因结论 -> 生成含功能点的 draft 落库(status=draft, author=auto)。
  (b) 无有效引用 / low_confidence 的结论 -> 不生成(守"只从引用提炼、不编造")。
  (c) 去重: 同 (task_id, product) 已有 draft -> 跳过, 不重复落库。
  (d) dry_run / 无 points 的归因 -> 返回空, 不硬造。

真正调 Claude 的提炼由人工冒烟(需 key+代理), 不入 CI。
"""
from __future__ import annotations
import tempfile
import unittest

from pipeline import store as STORE
from pipeline import method_synth as MS


def _attr(points, dry_run=False, engine="claude-opus-4-8"):
    return {"task_id": "T-x", "baseline": "vio", "dry_run": dry_run,
            "engine": engine, "points": points}


def _point(competitor="manus", conf="normal", cites=None):
    return {"competitor": competitor, "headline": "h", "detail": "d",
            "suspected_category": "feature-gap", "confidence": conf,
            "citations": cites if cites is not None
            else [{"product": competitor, "source_file": "log.md", "quote": "真实原文"}]}


class TestMethodSynth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.con = STORE.connect(self.tmp.name)
        # 挡掉真实 LLM: 提炼恒返回固定功能点(不打网络)。
        self._orig = MS._synthesize_one
        MS._synthesize_one = lambda p: {
            "feature_point": "接入联网检索工具,执行前先做资料调研",
            "suggestion": "vio 在执行前调用检索工具收集资料。"}

    def tearDown(self):
        MS._synthesize_one = self._orig
        self.con.close()

    def test_a_cited_point_creates_draft(self):
        created = MS.synthesize_from_attribution(self.con, "T-a", _attr([_point()]))
        self.assertEqual(len(created), 1)
        m = created[0]
        self.assertEqual(m["status"], "draft")
        self.assertEqual(m["author"], MS.AUTO_AUTHOR)
        self.assertIn("接入联网检索工具", m["draft"])
        self.assertIn("证据链(交付物/清单原文引用)", m["draft"])

    def test_b_no_citation_skipped(self):
        # 无引用 -> _synthesize_one 应返回 None; 这里让它对空引用真实走一遍。
        MS._synthesize_one = self._orig
        created = MS.synthesize_from_attribution(
            self.con, "T-b", _attr([_point(cites=[])]))
        self.assertEqual(created, [])

    def test_b2_low_confidence_skipped(self):
        MS._synthesize_one = self._orig
        created = MS.synthesize_from_attribution(
            self.con, "T-b2", _attr([_point(conf="low_confidence")]))
        self.assertEqual(created, [])

    def test_c_dedupe_no_double_insert(self):
        first = MS.synthesize_from_attribution(self.con, "T-c", _attr([_point()]))
        self.assertEqual(len(first), 1)
        # 再跑同题同竞品 -> 已有 draft, 跳过。
        again = MS.synthesize_from_attribution(self.con, "T-c", _attr([_point()]))
        self.assertEqual(again, [])
        rows = STORE.all_methods(self.con)
        self.assertEqual(len([r for r in rows if r["task_id"] == "T-c"]), 1)

    def test_d_dry_run_and_empty(self):
        self.assertEqual(MS.synthesize_from_attribution(
            self.con, "T-d", _attr([_point()], dry_run=True)), [])
        self.assertEqual(MS.synthesize_from_attribution(
            self.con, "T-d", _attr([])), [])
        self.assertEqual(MS.synthesize_from_attribution(self.con, "T-d", None), [])


if __name__ == "__main__":
    unittest.main()
