"""功能A 接线: vio_gap 结果 -> 方法初稿 (method_synth.synthesize_from_vio_gap) 离线单测.

LLM 提炼用 monkeypatch 注入固定功能点(不打网络):
  (a) capability-gap + 有引用 -> 落 draft(status=draft, author=auto, 标 vio_gap 来源)。
  (b) execution-gap / dry_run / low_confidence / 无引用 -> 不落(如实, 不硬造)。
  (c) 去重: 同 (task_id, 'vio') 已有 draft -> 跳过。
"""
from __future__ import annotations
import tempfile
import unittest

from pipeline import store as STORE
from pipeline import method_synth as MS


def _vg(**over):
    base = {"task_id": "TA4", "baseline": "vio", "verdict": "capability-gap",
            "headline": "vio 无 CRM 集成入口", "detail": "d", "confidence": "normal",
            "engine": "claude-opus-4-8",
            "citations": [{"product": "vio", "source_file": "log.md",
                           "quote": "没有 CRM 工具"}]}
    base.update(over)
    return base


class TestSynthFromVioGap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.con = STORE.connect(self.tmp.name)
        self._orig = MS._synthesize_one
        MS._synthesize_one = lambda p: {
            "feature_point": "接入 CRM 写入集成能力入口",
            "suggestion": "vio 增加 CRM API 集成模块。"}

    def tearDown(self):
        MS._synthesize_one = self._orig
        self.con.close()

    def test_a_capability_gap_creates_vio_draft(self):
        created = MS.synthesize_from_vio_gap(self.con, "TA4", _vg())
        self.assertEqual(len(created), 1)
        m = created[0]
        self.assertEqual(m["product"], "vio")
        self.assertEqual(m["status"], "draft")
        self.assertEqual(m["author"], MS.AUTO_AUTHOR)
        self.assertIn("能力空白", m["draft"])
        self.assertIn("vio_gap", m["draft"])

    def test_b_execution_gap_skipped(self):
        self.assertEqual(
            MS.synthesize_from_vio_gap(self.con, "TA5", _vg(verdict="execution-gap")), [])

    def test_c_dry_run_and_low_conf_skipped(self):
        self.assertEqual(
            MS.synthesize_from_vio_gap(self.con, "TA6", _vg(dry_run=True)), [])
        self.assertEqual(
            MS.synthesize_from_vio_gap(self.con, "TA7", _vg(confidence="low_confidence")), [])
        self.assertEqual(
            MS.synthesize_from_vio_gap(self.con, "TA8", _vg(citations=[])), [])

    def test_d_dedupe(self):
        first = MS.synthesize_from_vio_gap(self.con, "TA9", _vg())
        self.assertEqual(len(first), 1)
        again = MS.synthesize_from_vio_gap(self.con, "TA9", _vg())
        self.assertEqual(again, [])


if __name__ == "__main__":
    unittest.main()
