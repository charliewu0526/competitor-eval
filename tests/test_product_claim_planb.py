"""方案B: 领取粒度细化到「题×产品」(拆单法) 的行为测试。

验证外部行为, 不验实现细节:
  * 一道题拆成 N 个单产品领取单元 (每个产品一个), 参赛集 = GATE 派生。
  * 两人可分领同题的不同产品; 抢同一产品单元并发单赢 (product 级锁)。
  * 够不着的产品不给物化领取单元 (立身之本)。
  * 拆单后同题不同产品分属不同 assignment, 榜单/差距报告仍按 (task,product) 聚合对比。
  * 整题领取路径向后兼容 (materialize_for_task 仍可用)。
"""
from __future__ import annotations
import tempfile
import pathlib
import unittest

from pipeline import store
from pipeline import assignments as A
from pipeline import leaderboard as LB
from pipeline import gap_report as GR

TASK = "W1-sales-reconcile-dunning-001"   # professional-workflow, 参赛集 = [vio, claude]


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


class ProductLevelMaterialize(unittest.TestCase):
    def test_split_into_single_product_units(self):
        con = store.connect(_tmpdb())
        units = A.materialize_products_for_task(con, TASK)
        # 每个单元恰含一个产品; 覆盖整个参赛集。
        self.assertTrue(all(len(u["products"]) == 1 for u in units))
        prods = sorted(u["products"][0] for u in units)
        self.assertEqual(prods, ["claude", "vio"])
        self.assertTrue(all(u["status"] == "open" for u in units))

    def test_idempotent_on_task_product(self):
        con = store.connect(_tmpdb())
        a1 = A.materialize_product_for_task(con, TASK, "vio")
        a2 = A.materialize_product_for_task(con, TASK, "vio")
        self.assertEqual(a1["id"], a2["id"])   # 复用, 不新建

    def test_unreachable_product_rejected(self):
        con = store.connect(_tmpdb())
        # codebuddy 不在 W1 参赛集 -> 不物化 (够不着不硬拉进来打 0)。
        with self.assertRaises(A.AssignmentError):
            A.materialize_product_for_task(con, TASK, "codebuddy")


class ProductLevelClaim(unittest.TestCase):
    def test_two_people_claim_different_products(self):
        con = store.connect(_tmpdb())
        units = A.materialize_products_for_task(con, TASK)
        u_vio = next(u for u in units if u["products"] == ["vio"])
        u_cla = next(u for u in units if u["products"] == ["claude"])
        a1 = A.claim(con, u_vio["id"], "mwx")     # 马文萱
        a2 = A.claim(con, u_cla["id"], "cyh")     # 陈雨含
        self.assertEqual(a1["claimed_by"], "mwx")
        self.assertEqual(a2["claimed_by"], "cyh")

    def test_product_unit_concurrent_single_winner(self):
        con = store.connect(_tmpdb())
        u = A.materialize_product_for_task(con, TASK, "vio")
        A.claim(con, u["id"], "mwx")
        with self.assertRaises(A.IllegalTransition):
            A.claim(con, u["id"], "cyh")          # 第二人抢同一产品单元被拒


class SplitStillAggregates(unittest.TestCase):
    """拆单后同题两产品分属不同 assignment, 榜单/差距报告仍按 (task,product) 聚合。"""

    def test_leaderboard_and_gap_aggregate_across_assignments(self):
        con = store.connect(_tmpdb())
        # 模拟两个独立 assignment 各自收口 -> 各写一条 score(键=task+product)。
        for product, sample, h1 in (("vio", 0.9, 1.0), ("claude", 0.6, 0.8)):
            store.upsert_score(con, {
                "task_id": TASK, "product": product, "run_idx": 0,
                "gate": "native-operable", "scored": 1, "reason": "",
                "sample_score": sample, "h1_honesty": h1})
        lb = LB.leaderboard("vio", store.all_scores(con))
        got = {r["product"] for r in lb["ranking"]}
        self.assertEqual(got, {"vio", "claude"})   # 两产品都进榜对比
        rep = GR.from_store(con, TASK, baseline="vio")
        prods = {getattr(d, "product", None) for d in rep.score_diffs}
        self.assertIn("claude", prods)             # 差距报告含竞品做对比


class BackCompat(unittest.TestCase):
    def test_whole_task_materialize_still_works(self):
        con = store.connect(_tmpdb())
        a = A.materialize_for_task(con, TASK)      # 旧整题路径仍可用
        self.assertGreaterEqual(len(a["products"]), 2)


if __name__ == "__main__":
    unittest.main()
