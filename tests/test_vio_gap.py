"""功能A: vio 失败归因 (vio_gap) 离线单测.

只测不打网络的判定逻辑, LLM 调用用 monkeypatch 注入假判定:
  (a) capability-gap + 有效引用 -> 产 Finding(subject=vio, suspected=capability-gap)。
  (b) execution-gap -> 不产 Finding(归 bug/质量轴, 不重复灌新功能)。
  (c) capability-gap 但引用命不中原文 -> low_confidence, 不产 Finding(守铁律)。
  (d) 无交付物 / 无 key -> dry_run, 不硬造。
  (e) verdict 越界 -> 保守退回 execution-gap。

真正调 Claude 的判定由人工冒烟(需 key+代理), 不入 CI。
"""
from __future__ import annotations
import unittest

from pipeline import vio_gap as VG
from pipeline import gap_attribution as GA


class _Doc:
    """伪 ArtifactDoc: 只需 content 供逐字命中校验。"""
    def __init__(self, content, source_file="execution-log/EXECUTION_LOG.md"):
        self.product = "vio"
        self.source_file = source_file
        self.is_text = True
        self.content = content
        self.size = len(content or "")


_VIO_LOG = ("尝试打开系统日历应用,但 vio 没有日历集成工具,"
            "只能在本地文件里记录,无法写入 CRM。")


def _patch_llm(monkey_result):
    VG._claude_verdict = lambda prompt: monkey_result


class TestVioGap(unittest.TestCase):
    def setUp(self):
        self._orig = VG._claude_verdict

    def tearDown(self):
        VG._claude_verdict = self._orig

    def _run(self, res, docs=None):
        _patch_llm(res)
        return VG.classify_vio_failure(
            "TA4-crm-deal-capture-001", expected_text="把成交写入 CRM",
            vio_docs=docs if docs is not None else [_Doc(_VIO_LOG)])

    def test_a_capability_gap_with_citation_makes_finding(self):
        r = self._run({"verdict": "capability-gap",
                       "headline": "vio 无 CRM 集成入口",
                       "detail": "日志显示它没有写入 CRM 的工具",
                       "citations": [{"source_file": "execution-log/EXECUTION_LOG.md",
                                      "quote": "vio 没有日历集成工具"}]})
        self.assertEqual(r.verdict, "capability-gap")
        self.assertEqual(r.confidence, "normal")
        self.assertIsNotNone(r.finding)
        self.assertEqual(r.finding["suspected_category"], "capability-gap")
        self.assertEqual(r.finding["subject"], "vio")
        self.assertEqual(r.finding["rule"], "vio-capability-gap")
        self.assertTrue(r.finding["evidence"])

    def test_b_execution_gap_no_finding(self):
        r = self._run({"verdict": "execution-gap",
                       "headline": "打开了 CRM 但填错字段",
                       "detail": "有入口, 执行没到位",
                       "citations": [{"source_file": "execution-log/EXECUTION_LOG.md",
                                      "quote": "vio 没有日历集成工具"}]})
        self.assertEqual(r.verdict, "execution-gap")
        self.assertIsNone(r.finding)

    def test_c_capability_gap_bad_citation_low_conf_no_finding(self):
        # 引用原文命不中 vio 交付物 -> low_confidence, 不产 Finding。
        r = self._run({"verdict": "capability-gap", "headline": "h", "detail": "d",
                       "citations": [{"source_file": "x.md",
                                      "quote": "这段原文根本不在日志里编造的引用"}]})
        self.assertEqual(r.verdict, "capability-gap")
        self.assertEqual(r.confidence, "low_confidence")
        self.assertIsNone(r.finding)

    def test_d_dry_run_no_docs(self):
        r = self._run({"verdict": "capability-gap", "headline": "h", "detail": "d",
                       "citations": []}, docs=[])
        self.assertTrue(r.dry_run)
        self.assertIsNone(r.finding)

    def test_d2_dry_run_flag_from_llm(self):
        r = self._run({"__dry_run__": True})
        self.assertTrue(r.dry_run)
        self.assertIsNone(r.finding)

    def test_e_out_of_range_verdict_falls_back_execution(self):
        r = self._run({"verdict": "nonsense", "headline": "h", "detail": "d",
                       "citations": [{"source_file": "execution-log/EXECUTION_LOG.md",
                                      "quote": "vio 没有日历集成工具"}]})
        self.assertEqual(r.verdict, "execution-gap")
        self.assertIsNone(r.finding)

    def test_f_unparseable_output_dry_run(self):
        r = self._run({"error": "unparseable", "raw": "..."})
        self.assertTrue(r.dry_run)


if __name__ == "__main__":
    unittest.main()
