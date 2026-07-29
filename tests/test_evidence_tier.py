"""B 交付物降级归因: 证据档位判定 + confidence 封顶 离线单测.

不打网络。只测档位判定 + confidence 封顶的纯逻辑:
  (a) 有执行日志 -> process-level, confidence 可到 normal。
  (b) 仅成品交付物(无日志) -> artifact-level, confidence 封顶 tentative(< normal)。
  (c) 都无 -> unavailable。
  (d) vio_gap 端到端: monkeypatch LLM, 仅成品的 vio 失败题 -> tier=artifact-level 且
      capability-gap 结论 confidence 不到 normal。
"""
from __future__ import annotations
import unittest

from pipeline import gap_attribution as GA
from pipeline import vio_gap as VG


class _Doc:
    def __init__(self, source_file, content="内容原文片段"):
        self.product = "vio"
        self.source_file = source_file
        self.is_text = True
        self.content = content
        self.size = len(content)


class TestEvidenceTier(unittest.TestCase):
    def test_a_log_is_process_level(self):
        docs = {"vio": [_Doc("execution-log/EXECUTION_LOG.md")],
                "manus": [_Doc("artifact/result.md")]}
        self.assertEqual(GA.evidence_tier(docs, ["manus"]), GA.PROCESS_LEVEL)

    def test_b_artifact_only(self):
        docs = {"vio": [_Doc("artifact/out.md")],
                "manus": [_Doc("artifact/result.md")]}
        self.assertEqual(GA.evidence_tier(docs, ["manus"]), GA.ARTIFACT_LEVEL)

    def test_c_unavailable(self):
        self.assertEqual(GA.evidence_tier({"vio": [], "manus": []}, ["manus"]),
                         GA.TIER_UNAVAILABLE)

    def test_d_confidence_cap(self):
        # process-level 不压 normal
        self.assertEqual(GA._cap_confidence_by_tier("normal", GA.PROCESS_LEVEL), "normal")
        # artifact-level 把 normal 压到 tentative
        self.assertEqual(GA._cap_confidence_by_tier("normal", GA.ARTIFACT_LEVEL), "tentative")
        # 已低于上限的不动
        self.assertEqual(GA._cap_confidence_by_tier("low_confidence", GA.ARTIFACT_LEVEL),
                         "low_confidence")
        # unavailable 压到 low_confidence
        self.assertEqual(GA._cap_confidence_by_tier("normal", GA.TIER_UNAVAILABLE),
                         "low_confidence")

    def test_e_vio_gap_artifact_level_caps_conf(self):
        # 仅成品(无日志)的 vio 失败题, capability-gap + 命中引用, confidence 应被压到 tentative
        docs = [_Doc("artifact/out.md", content="vio 没有 CRM 集成工具")]
        VG._claude_verdict = lambda prompt: {
            "verdict": "capability-gap", "headline": "vio 无 CRM 入口", "detail": "d",
            "citations": [{"source_file": "artifact/out.md", "quote": "vio 没有 CRM 集成工具"}]}
        r = VG.classify_vio_failure("TA4", expected_text="写入CRM", vio_docs=docs)
        self.assertEqual(r.evidence_tier, GA.ARTIFACT_LEVEL)
        self.assertEqual(r.confidence, "tentative")
        # tentative 仍算有引用支撑, capability-gap 应产 Finding
        self.assertIsNotNone(r.finding)

    def test_f_vio_gap_process_level_keeps_normal(self):
        docs = [_Doc("execution-log/EXECUTION_LOG.md", content="vio 没有 CRM 集成工具")]
        VG._claude_verdict = lambda prompt: {
            "verdict": "capability-gap", "headline": "h", "detail": "d",
            "citations": [{"source_file": "execution-log/EXECUTION_LOG.md",
                           "quote": "vio 没有 CRM 集成工具"}]}
        r = VG.classify_vio_failure("TA4", expected_text="x", vio_docs=docs)
        self.assertEqual(r.evidence_tier, GA.PROCESS_LEVEL)
        self.assertEqual(r.confidence, "normal")


if __name__ == "__main__":
    unittest.main()
