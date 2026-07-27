"""MR-12 (#48): 能力域分维度榜单 + 版本/日期/stale (ADR-0017).

Run: python -m unittest tests.test_domain_board_mr12 -v

Acceptance (issue #48):
  - 榜单按能力域分成多个维度榜 (同域才同台, Violoop 全域参赛)
  - 每条分数显示 competitor_version + tested_at
  - 超期分数标 stale, 不冒充现状
  - cannot-reach 的产品在榜上标「未参赛」(excluded) 而非 0 分垫底

好测试只验外部行为: 喂扁平 score 列表 + task->domain 映射, 断言分维度榜的分桶、
新鲜度透传、stale 派生、cannot-reach 归 excluded。评分核心不新增测试 (它没改)。
"""
from __future__ import annotations
import time
import unittest

from pipeline import domain_board as DB


NOW = 1_700_000_000.0
DAY = 86400.0


def _score(task, product, *, domain=None, gate="native-operable", sample=None,
           h1=None, scored=True, reason=None, version=None, tested_at=None,
           stale=False, run_idx=1):
    # domain 只用于测试组织, 不进 score dict (域映射走 task_domains 参数)。
    return {"task_id": task, "product": product, "run_idx": run_idx,
            "gate": gate, "scored": scored, "reason": reason,
            "objective_ratio": 1.0, "sample_score": sample, "h1_honesty": h1,
            "competitor_version": version, "tested_at": tested_at, "stale": stale}


class Freshness(unittest.TestCase):
    def test_stored_stale_flag_wins(self):
        # 人工/半自动存过的 stale=True 恒生效, 即便日期很新。
        self.assertTrue(DB.is_stale(NOW, True, now=NOW))

    def test_missing_tested_at_not_auto_stale(self):
        # tested_at 缺失 => 不擅自判新鲜也不伪装陈旧, 沿用 stored 标志 (这里 False)。
        self.assertFalse(DB.is_stale(None, False, now=NOW))
        self.assertTrue(DB.is_stale(None, True, now=NOW))

    def test_within_window_fresh(self):
        self.assertFalse(DB.is_stale(NOW - 10 * DAY, False, now=NOW, window_days=90))

    def test_beyond_window_stale(self):
        self.assertTrue(DB.is_stale(NOW - 120 * DAY, False, now=NOW, window_days=90))


class DomainSplit(unittest.TestCase):
    def _board(self):
        scores = [
            # 办公套件域: vio vs codebuddy
            _score("T-office", "vio", sample=0.8, tested_at=NOW - 5 * DAY, version="v2.1"),
            _score("T-office", "codebuddy", sample=0.6, tested_at=NOW - 5 * DAY, version="1.0.0"),
            # 网页任务域: vio vs operator, operator 版本陈旧
            _score("T-web", "vio", sample=0.7, tested_at=NOW - 3 * DAY, version="v2.1"),
            _score("T-web", "operator", sample=0.9, tested_at=NOW - 200 * DAY, version="2024-08"),
        ]
        task_domains = {"T-office": "office-suite", "T-web": "browser-web"}
        return DB.build_domain_board(scores, task_domains, now=NOW, window_days=90)

    def test_split_into_multiple_domain_boards(self):
        b = self._board()
        domains = [x["domain"] for x in b["boards"]]
        self.assertIn("office-suite", domains)
        self.assertIn("browser-web", domains)
        self.assertEqual(len(b["boards"]), 2)

    def test_domain_order_follows_enum(self):
        # office-suite 在 browser-web 之前 (CAPABILITY_DOMAIN_VALUES 子序列顺序)。
        b = self._board()
        self.assertEqual([x["domain"] for x in b["boards"]],
                         ["office-suite", "browser-web"])

    def test_labels_are_plain_chinese(self):
        b = self._board()
        office = next(x for x in b["boards"] if x["domain"] == "office-suite")
        self.assertIn("办公套件", office["label"])
        self.assertTrue(office["hint"])

    def test_baseline_participates_every_domain(self):
        # Violoop 全域参赛: 每张域榜的 ranking 都含 vio。
        b = self._board()
        for board in b["boards"]:
            prods = [r["product"] for r in board["leaderboard"]["ranking"]]
            self.assertIn("vio", prods)

    def test_version_and_tested_at_travel_to_board(self):
        b = self._board()
        web = next(x for x in b["boards"] if x["domain"] == "browser-web")
        cell = web["freshness"]["T-web|operator"]
        self.assertEqual(cell["competitor_version"], "2024-08")
        self.assertEqual(cell["tested_at"], NOW - 200 * DAY)

    def test_stale_derived_from_tested_at(self):
        b = self._board()
        web = next(x for x in b["boards"] if x["domain"] == "browser-web")
        # operator 200 天前测, 超 90 天窗 => stale;vio 3 天前 => fresh。
        self.assertTrue(web["freshness"]["T-web|operator"]["stale"])
        self.assertFalse(web["freshness"]["T-web|vio"]["stale"])
        # product 行也标陈旧 (最保守: 有一条旧就提醒)。
        self.assertTrue(web["product_freshness"]["operator"]["stale"])
        self.assertFalse(web["product_freshness"]["vio"]["stale"])

    def test_same_product_appears_in_multiple_domains(self):
        # vio 同时出现在两张域榜 —— 多维度榜单应有之义。
        b = self._board()
        appearances = sum(
            1 for board in b["boards"]
            if any(r["product"] == "vio" for r in board["leaderboard"]["ranking"]))
        self.assertEqual(appearances, 2)


class CannotReach(unittest.TestCase):
    def test_cannot_reach_marked_not_zero(self):
        # 桌面题考云端 agent: cannot-reach 归 excluded, 不进 ranking (非 0 分垫底)。
        scores = [
            _score("T-desk", "vio", sample=0.8, tested_at=NOW),
            _score("T-desk", "cloud_agent", gate="cannot-reach", sample=None,
                   scored=False, reason="cannot-reach"),
        ]
        task_domains = {"T-desk": "computer-control"}
        b = DB.build_domain_board(scores, task_domains, now=NOW)
        board = next(x for x in b["boards"] if x["domain"] == "computer-control")
        prods = [r["product"] for r in board["leaderboard"]["ranking"]]
        self.assertNotIn("cloud_agent", prods)          # 未参赛, 不排名
        excl = board["leaderboard"]["excluded"]
        self.assertEqual(len(excl), 1)
        self.assertEqual(excl[0]["product"], "cloud_agent")
        self.assertEqual(excl[0]["reason"], "cannot-reach")


class Ungrouped(unittest.TestCase):
    def test_unknown_task_domain_not_silently_dropped(self):
        # task_domains 查不到的分数归 ungrouped, 不静默消失。
        scores = [_score("T-mystery", "vio", sample=0.5, tested_at=NOW)]
        b = DB.build_domain_board(scores, {}, now=NOW)
        self.assertEqual(b["boards"], [])
        self.assertEqual(len(b["ungrouped"]), 1)
        self.assertIsNone(b["ungrouped"][0]["domain"])
        prods = [r["product"] for r in b["ungrouped"][0]["leaderboard"]["ranking"]]
        self.assertIn("vio", prods)


class EmptyInput(unittest.TestCase):
    def test_empty_scores_clean_board(self):
        b = DB.build_domain_board([], {}, now=NOW)
        self.assertEqual(b["boards"], [])
        self.assertEqual(b["ungrouped"], [])
        self.assertEqual(b["window_days"], DB.DEFAULT_FRESHNESS_DAYS)


if __name__ == "__main__":
    unittest.main()
