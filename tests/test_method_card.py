"""A 结论结构化: 方法卡片六段 + 缺字段待补 + 优先级粗分档 离线单测.

不打网络。_synthesize_one 用 monkeypatch 注入结构化卡片:
  (a) 满字段 -> 渲染六段齐全(功能点/范围/验收/优先级/竞品做法/证据链)。
  (b) LLM 只回部分字段 -> 缺的如实标待补(_TODO), 不编造。
  (c) feature_point 空 -> 整条不成立(None)。
  (d) _compute_priority: 关联多题/多域 -> 高; 单题单域 -> 低。
"""
from __future__ import annotations
import tempfile
import unittest

from pipeline import store as STORE
from pipeline import method_synth as MS


def _point(cat="capability-gap"):
    return {"competitor": "town", "headline": "h", "detail": "d",
            "suspected_category": cat, "confidence": "normal",
            "citations": [{"product": "town", "source_file": "cap.md", "quote": "证据"}]}


class TestMethodCard(unittest.TestCase):
    def test_a_full_card_renders_six_sections(self):
        synth = {"feature_point": "接入 CRM 写入集成", "scope": "只做写入不做双向同步",
                 "acceptance": "能把成交写进 CRM 并回读校验", "rival_practice": "town 用 HubSpot API",
                 "suggestion": "vio 增加 CRM 连接器"}
        d = MS._render_draft(_point(), synth, "eng", source="capability_census",
                             priority="高", priority_note="关联 3 题")
        # cap-gap 场景落地建议段标题是「能力空白落地建议」(非 cap-gap 才是「竞品做法」)
        for h in ("## 功能点", "## 范围边界", "## 验收标准", "## 优先级 · 影响面",
                  "落地建议", "## 证据链"):
            self.assertIn(h, d)
        self.assertIn("竞品做法:", d)   # 竞品做法作为条目出现在落地建议段内
        self.assertIn("接入 CRM 写入集成", d)
        self.assertIn("优先级: 高", d)
        self.assertNotIn(MS._TODO, d)   # 满字段不该有待补

    def test_b_missing_fields_marked_todo(self):
        synth = {"feature_point": "接入 CRM", "scope": "", "acceptance": "",
                 "rival_practice": "", "suggestion": ""}
        d = MS._render_draft(_point(), synth, "eng")
        self.assertIn(MS._TODO, d)      # 缺字段如实标待补
        self.assertIn("接入 CRM", d)

    def test_c_empty_feature_point_is_none(self):
        MS_orig = MS._synthesize_one
        # 直接测 _synthesize_one 的守卫: 造一个 LLM 返回空 feature_point 的场景
        import pipeline.gap_attribution as GA
        orig = GA._post_via_proxy
        import os
        os.environ["CLAUDE_API_KEY"] = "k"
        GA._post_via_proxy = lambda *a, **k: {"content": [{"text": '{"feature_point":"","scope":"x"}'}]}
        try:
            self.assertIsNone(MS._synthesize_one(_point()))
        finally:
            GA._post_via_proxy = orig
            del os.environ["CLAUDE_API_KEY"]

    def test_d_priority_tiers(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        con = STORE.connect(tmp.name)
        # 造 3 条不同 task 的 capability-gap finding(同 subject) -> 高
        from pipeline.findings import make_finding
        for tid in ("census-town-a", "matrix-office-suite-b", "T10-x"):
            f = make_finding(task_id=tid, rule="r", suspected_category="capability-gap",
                             subject="town", phenomenon="p",
                             evidence=[{"source": "s", "ref": "r"}])
            STORE.upsert_finding(con, f.as_dict())
        tier, note = MS._compute_priority(con, "town", "cap")
        self.assertEqual(tier, "高")
        # 单题单域 -> 低
        tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        con2 = STORE.connect(tmp2.name)
        f = make_finding(task_id="T10-only", rule="r", suspected_category="capability-gap",
                         subject="solo", phenomenon="p", evidence=[{"source": "s", "ref": "r"}])
        STORE.upsert_finding(con2, f.as_dict())
        tier2, _ = MS._compute_priority(con2, "solo", "cap")
        self.assertEqual(tier2, "低")
        con.close(); con2.close()


if __name__ == "__main__":
    unittest.main()
