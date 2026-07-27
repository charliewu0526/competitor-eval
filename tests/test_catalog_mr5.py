"""MR-5 (#41): 任务清单目录 — 按能力域分组浏览 (只读派生视图).

验证外部行为, 不验实现细节:
  * build_catalog 按 capability_domain 分组, 域顺序稳定, 空域不出现.
  * 每题带中立标准 Prompt + 说明 + core_assertions.
  * 参赛竞品由 GATE 派生 (gate.gate_for): cannot-reach 不进参赛集, 但仍列出
    (带 gate 标注), 够不着不硬拉进来打 0.
  * 按能力域筛选 = 取对应组.
  * task_detail 单题详情; 找不到返回 None.
  * 至少两个能力域各有真实预置任务卡 (X1 合规, 由 discover 校验).

Run: python -m unittest tests.test_catalog_mr5 -v
"""
from __future__ import annotations
import unittest

from pipeline import catalog as CAT
from pipeline.registry_fakes import FakeRegistry
from pipeline.registry import Competitor
from pipeline.schema import CAPABILITY_DOMAIN_VALUES


class BuildCatalog(unittest.TestCase):
    def setUp(self):
        self.groups = CAT.build_catalog()
        self.by_domain = {g["domain"]: g for g in self.groups}

    def test_groups_are_by_capability_domain(self):
        # 每组的 domain 是合法能力域, 且组内每题的 capability_domain 与组一致.
        for g in self.groups:
            self.assertIn(g["domain"], CAPABILITY_DOMAIN_VALUES)
            self.assertTrue(g["tasks"])          # 空域不出现
            for t in g["tasks"]:
                self.assertEqual(t["capability_domain"], g["domain"])

    def test_domain_order_follows_schema(self):
        # 域顺序 = CAPABILITY_DOMAIN_VALUES 的子序列 (稳定, 不随字典乱序).
        order = [g["domain"] for g in self.groups]
        ranks = [CAPABILITY_DOMAIN_VALUES.index(d) for d in order]
        self.assertEqual(ranks, sorted(ranks))

    def test_at_least_two_domains_present(self):
        # story 7 + 「同域才同台」: 预置任务跨 >=2 个能力域 (T1/T2/T3).
        self.assertGreaterEqual(len(self.groups), 2)

    def test_each_task_carries_neutral_prompt_and_desc(self):
        for g in self.groups:
            for t in g["tasks"]:
                self.assertTrue(t["prompt"].strip())        # 中立标准 Prompt
                self.assertIsInstance(t["core_assertions"], list)
                self.assertTrue(t["core_assertions"])        # 详细判定点
                self.assertIn("readme", t)                   # 详细说明字段在

    def test_domain_carries_human_label_and_hint(self):
        for g in self.groups:
            self.assertTrue(g["label"].strip())
            self.assertIn("hint", g)

    def test_t1_in_wechat_domain(self):
        self.assertIn("wechat-im", self.by_domain)
        ids = {t["task_id"] for t in self.by_domain["wechat-im"]["tasks"]}
        self.assertIn("T1-wechat-send-001", ids)

    def test_office_and_web_presets_present(self):
        self.assertIn("office-suite", self.by_domain)
        self.assertIn("browser-web", self.by_domain)
        office = {t["task_id"] for t in self.by_domain["office-suite"]["tasks"]}
        web = {t["task_id"] for t in self.by_domain["browser-web"]["tasks"]}
        self.assertIn("T2-excel-sum-001", office)
        self.assertIn("T3-web-extract-001", web)


class GateDerivedParticipation(unittest.TestCase):
    """参赛集由 GATE 派生, 不预先排除, 够不着不打 0."""

    def _reg(self):
        # 一个能操作桌面 (vio) + 一个云端 only (cloud) 的混合登记表.
        return FakeRegistry([
            Competitor("vio", "Violoop", can_operate_local_desktop=True),
            Competitor("cloud", "CloudOnly", can_operate_local_desktop=False),
        ])

    def test_desktop_task_excludes_cloud_from_participation(self):
        # requires_local_desktop=True 的题 (T1/T2): 云端 only -> cannot-reach,
        # 不进 participating, 但仍在 competitors 里带 gate 标注 (透明, 非删除).
        groups = CAT.build_catalog(registry=self._reg())
        by = {g["domain"]: g for g in groups}
        t2 = next(t for t in by["office-suite"]["tasks"]
                  if t["task_id"] == "T2-excel-sum-001")
        self.assertIn("vio", t2["participating"])
        self.assertNotIn("cloud", t2["participating"])
        cloud = next(c for c in t2["competitors"] if c["id"] == "cloud")
        self.assertEqual(cloud["gate"], "cannot-reach")
        self.assertFalse(cloud["reachable"])

    def test_web_task_keeps_cloud_as_cross_layer(self):
        # requires_local_desktop=False 的题 (T3): 云端 only -> api-or-integration
        # (跨层), 仍参赛 (reachable=True), 不被当 cannot-reach 丢掉.
        groups = CAT.build_catalog(registry=self._reg())
        by = {g["domain"]: g for g in groups}
        t3 = next(t for t in by["browser-web"]["tasks"]
                  if t["task_id"] == "T3-web-extract-001")
        cloud = next(c for c in t3["competitors"] if c["id"] == "cloud")
        self.assertEqual(cloud["gate"], "api-or-integration")
        self.assertTrue(cloud["reachable"])
        self.assertTrue(cloud["cross_layer"])
        self.assertIn("cloud", t3["participating"])


class FilterAndDetail(unittest.TestCase):
    def test_filter_by_domain_is_group_selection(self):
        groups = CAT.build_catalog()
        web = [g for g in groups if g["domain"] == "browser-web"]
        self.assertEqual(len(web), 1)
        self.assertTrue(all(t["capability_domain"] == "browser-web"
                            for t in web[0]["tasks"]))

    def test_task_detail_returns_card(self):
        card = CAT.task_detail("T1-wechat-send-001")
        self.assertIsNotNone(card)
        self.assertEqual(card["task_id"], "T1-wechat-send-001")
        self.assertTrue(card["prompt"].strip())
        self.assertTrue(card["competitors"])

    def test_task_detail_missing_returns_none(self):
        self.assertIsNone(CAT.task_detail("nope-does-not-exist"))


if __name__ == "__main__":
    unittest.main()
