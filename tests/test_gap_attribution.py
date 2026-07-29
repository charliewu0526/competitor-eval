"""差距归因层 (gap_attribution) 离线单测.

只测**不打网络**的两块地基 —— 立身之本的机器闸:
  1. 引用命中校验: LLM 声称的引用必须能在交付物原文里逐字命中, 否则剔除;
     一条结论若无任何有效引用 -> 标 low_confidence (防编造出处)。
  2. suspected_category 只落三类白名单, 越界归 execution-detail (不另造判定)。

真正调 Claude 的 attribute_task 端到端由人工冒烟验证 (需 key + 代理), 不入 CI。
"""
from __future__ import annotations
import unittest

from pipeline import gap_attribution as GA


def _doc(product, source_file, content):
    return GA.ArtifactDoc(product=product, source_file=source_file,
                          is_text=True, content=content, size=len(content or ""))


class TestCitationGate(unittest.TestCase):
    def setUp(self):
        self.docs_by_prod = {
            "manus": [_doc("manus", "log.md", "使用 EXIF DateTimeOriginal 读取拍摄时间")],
            "vio": [_doc("vio", "session.json", "reused rename_photos.py")],
        }

    def test_valid_citation_kept_and_normal(self):
        raw = [{"competitor": "manus", "headline": "h", "detail": "d",
                "suspected_category": "feature-gap",
                "citations": [{"product": "manus", "source_file": "log.md",
                               "quote": "使用 EXIF DateTimeOriginal 读取拍摄时间"}]}]
        pts = GA._validate_points(raw, self.docs_by_prod)
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0].confidence, "normal")
        self.assertEqual(len(pts[0].citations), 1)
        self.assertEqual(pts[0].suspected_category, "feature-gap")

    def test_fabricated_citation_dropped_low_confidence(self):
        # 引用文本在交付物里不存在 -> 剔除 -> 无有效引用 -> low_confidence。
        raw = [{"competitor": "manus", "headline": "h", "detail": "d",
                "suspected_category": "feature-gap",
                "citations": [{"product": "manus", "source_file": "log.md",
                               "quote": "这句话交付物里根本没有,是编造的"}]}]
        pts = GA._validate_points(raw, self.docs_by_prod)
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0].confidence, "low_confidence")
        self.assertEqual(len(pts[0].citations), 0)

    def test_unknown_category_falls_back(self):
        raw = [{"competitor": "manus", "headline": "h", "detail": "d",
                "suspected_category": "made-up-category", "citations": []}]
        pts = GA._validate_points(raw, self.docs_by_prod)
        self.assertEqual(pts[0].suspected_category, "execution-detail")

    def test_empty_points(self):
        self.assertEqual(GA._validate_points([], self.docs_by_prod), [])
        self.assertEqual(GA._validate_points(None, self.docs_by_prod), [])


class TestArtifactCollection(unittest.TestCase):
    def test_missing_artifacts_returns_empty(self):
        # 不存在的题/产品 -> 空列表 (如实, 不炸)。
        docs = GA.collect_artifacts("NO-SUCH-TASK-999", "nobody")
        self.assertEqual(docs, [])

    def test_load_expected_missing_returns_empty_str(self):
        self.assertEqual(GA.load_expected("NO-SUCH-TASK-999"), "")


if __name__ == "__main__":
    unittest.main()
