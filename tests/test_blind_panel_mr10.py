"""MR-10 (#46): 送面板前打乱标签 + 独立打分接线 (ADR-0012).

Run: python -m unittest tests.test_blind_panel_mr10 -v

Acceptance (issue #46), all OFFLINE:
  AC1 送面板前产品标签被打乱为 Product A/B/C(不用注册序,基准不恒为 A)
  AC2 每份交付物独立打分,不做成对对比
  AC3 面板输入用脱敏版日志/证据,不泄露产品身份
  AC4 端到端:真实 Submission → 独立盲评分数落库(按真实 id,带版本/日期)
"""
from __future__ import annotations
import pathlib
import random
import tempfile
import unittest

from pipeline import blind_panel as BP
from pipeline import orchestrate
from pipeline import intake as IN
from pipeline import intake_fakes as IF
from pipeline import objective as O
from pipeline import store as STORE
from pipeline import leaderboard as LB
from pipeline import review_fakes as RF
from pipeline.registry import Competitor, blind_letter
from pipeline.registry_fakes import make_fake_registry
from pipeline.schema import TaskSpec


class _TaskMeta:
    """Duck-typed suite.LoadedTask: a TaskSpec + assertions callable (T1 shape)."""

    def __init__(self, spec):
        self.task_spec = spec

    def assertions(self):
        return [
            O.manual_check("target contact received the exact message",
                           "msg_received", primary=True),
            O.manual_check("message text matches exactly", "text_exact",
                           primary=True),
            O.manual_check("no other contact was messaged", "no_collateral",
                           primary=False),
        ]


def _t1_spec():
    return TaskSpec(task_id="T1-wechat-send-001", domain="1", app="wechat",
                    prompt="send msg", core_assertions=["primary"],
                    requires_local_desktop=True, capability_domain="wechat-im")


class _OfflinePanel(unittest.TestCase):
    """Pin the fake review panel so score_run never dials the network, and
    CAPTURE every prompt each panelist receives (to assert redaction AC3)."""

    def setUp(self):
        self.prompts: list[str] = []
        self._orig_panel = orchestrate.PANELISTS
        self._saved = {}

        def _spy(name, inner):
            def _fn(prompt):
                self.prompts.append(prompt)
                return inner(prompt)
            return _fn

        for n, fn in RF.FAKE_PANEL.items():
            self._saved[n] = getattr(orchestrate, n, None)
            setattr(orchestrate, n, _spy(n, fn))
        orchestrate.PANELISTS = tuple(RF.FAKE_PANEL.keys())

    def tearDown(self):
        orchestrate.PANELISTS = self._orig_panel
        for n, v in self._saved.items():
            if v is None:
                if hasattr(orchestrate, n):
                    delattr(orchestrate, n)
            else:
                setattr(orchestrate, n, v)


# =============================================================================
# AC1: 送面板前打乱标签 —— 复用 blind_letter 取值,但顺序随机、基准不恒为 A。
# =============================================================================
class ShuffleBlindLabels(unittest.TestCase):
    def test_labels_are_a_bijection_over_products(self):
        m = BP.shuffle_blind_labels(["vio", "open_interpreter", "simular"], seed=1)
        self.assertEqual(set(m), {"vio", "open_interpreter", "simular"})
        # 标签集合就是 blind_letter 的前 N 个,配对被打乱但取值不新造。
        self.assertEqual(set(m.values()),
                         {blind_letter(0), blind_letter(1), blind_letter(2)})
        self.assertEqual(len(set(m.values())), 3)  # 无撞标签

    def test_dedups_products(self):
        m = BP.shuffle_blind_labels(["vio", "vio", "simular"], seed=0)
        self.assertEqual(set(m), {"vio", "simular"})
        self.assertEqual(len(set(m.values())), 2)

    def test_order_is_actually_shuffled_not_registration_order(self):
        # 立身之本:若用注册序,vio 恒为 Product A,面板按位置就能反推自家。
        # across many seeds, vio must NOT always land on Product A.
        prods = ["vio", "open_interpreter", "simular", "manus"]
        vio_labels = {BP.shuffle_blind_labels(prods, seed=s)["vio"]
                      for s in range(30)}
        self.assertGreater(len(vio_labels), 1,
                           "vio 的盲标签在所有 seed 下都相同 => 没真打乱,面板可反推")

    def test_seed_is_reproducible(self):
        a = BP.shuffle_blind_labels(["vio", "simular"], seed=42)
        b = BP.shuffle_blind_labels(["vio", "simular"], seed=42)
        self.assertEqual(a, b)


# =============================================================================
# AC2: 每份交付物独立打分,不做成对对比。
# =============================================================================
class IndependentScoring(_OfflinePanel):
    def setUp(self):
        super().setUp()
        self.reg = make_fake_registry()
        self.meta = _TaskMeta(_t1_spec())
        self.tr = IF.make_fake_translator()

    def test_each_submission_scored_once_independently(self):
        subs = [IF.make_fake_submission("vio"),
                IF.make_fake_submission("simular")]
        res = BP.score_submissions(subs, self.meta, self.reg, translator=self.tr,
                                   seed=7)
        self.assertEqual(len(res), 2)
        self.assertEqual({b.product for b in res}, {"vio", "simular"})
        # 每份都有自己独立的 score dict,产品 id 按真实身份归位。
        for b in res:
            self.assertEqual(b.score["product"], b.product)
            self.assertTrue(b.score["scored"])

    def test_score_independent_of_other_products_present(self):
        # 独立打分的判据:一个产品的分数不因同批里有没有别的产品而变化
        # (成对对比会让 A 的分数依赖 B —— 这里必须不依赖)。
        vio_alone = BP.score_submissions([IF.make_fake_submission("vio")],
                                         self.meta, self.reg, translator=self.tr,
                                         seed=1)
        vio_with_others = BP.score_submissions(
            [IF.make_fake_submission("vio"), IF.make_fake_submission("simular")],
            self.meta, self.reg, translator=self.tr, seed=1)
        s_alone = next(b.score["sample_score"] for b in vio_alone
                       if b.product == "vio")
        s_grouped = next(b.score["sample_score"] for b in vio_with_others
                         if b.product == "vio")
        self.assertEqual(s_alone, s_grouped)

    def test_primary_fail_still_independent_zero(self):
        subs = [IF.make_fake_submission("vio", msg_received=False),
                IF.make_fake_submission("simular")]
        res = BP.score_submissions(subs, self.meta, self.reg, translator=self.tr,
                                   seed=3)
        vio = next(b for b in res if b.product == "vio")
        self.assertTrue(vio.run.objective_failed_primary)
        self.assertEqual(vio.score["sample_score"], 0.0)


# =============================================================================
# AC3: 面板输入用脱敏版 —— process evidence 不含品牌 / 模型指纹。
# =============================================================================
class PanelSeesRedacted(_OfflinePanel):
    def setUp(self):
        super().setUp()
        self.reg = make_fake_registry()
        self.meta = _TaskMeta(_t1_spec())
        # 用一个 transcript / artifact 里塞满品牌+模型指纹的 submission。
        self.tr = IF.make_fake_translator()

    def _leaky_submission(self, product):
        sub = IF.make_fake_submission(product)
        # transcript 泄底:含品牌名 (Simular/Violoop) + 模型名 (fake-model)。
        sub.transcript_excerpt = ("Violoop opened WeChat; Simular fell back; "
                                  "model fake-model produced the reply.")
        return sub

    def test_panel_prompt_contains_blind_label_not_real_id(self):
        subs = [self._leaky_submission("vio"), self._leaky_submission("simular")]
        res = BP.score_submissions(subs, self.meta, self.reg, translator=self.tr,
                                   ctx_by_product={
                                       "vio": {"artifact_summary": "Violoop sent it"},
                                       "simular": {"artifact_summary": "Simular sent it"}},
                                   seed=5)
        joined = "\n".join(self.prompts)
        # 面板 prompt 里必须出现打乱后的盲标签……
        for b in res:
            self.assertIn(b.blind_label, joined)

    def test_brand_and_model_fingerprints_scrubbed_from_panel(self):
        subs = [self._leaky_submission("vio"), self._leaky_submission("simular")]
        BP.score_submissions(subs, self.meta, self.reg, translator=self.tr,
                             ctx_by_product={
                                 "vio": {"artifact_summary": "Violoop sent it",
                                         "screenshots_note": "screenshot by Violoop"},
                                 "simular": {"artifact_summary": "Simular sent it"}},
                             seed=5)
        joined = "\n".join(self.prompts)
        # 洗漏 = 破盲 = 高风险回归:品牌 / 模型指纹绝不能出现在面板看到的文本里。
        for leak in ("Violoop", "Simular", "fake-model"):
            self.assertNotIn(leak, joined,
                             f"品牌/模型指纹 {leak!r} 泄露给了盲评面板 => 破盲")

    def test_raw_run_kept_unredacted_for_persistence(self):
        # 脱敏只作用于送面板一瞬;落库/抽查用的原始 run 保留真身(成本/抽查要真数据)。
        subs = [self._leaky_submission("vio")]
        res = BP.score_submissions(subs, self.meta, self.reg, translator=self.tr,
                                   seed=5)
        self.assertIn("Violoop", res[0].run.transcript_excerpt)


# =============================================================================
# AC4: 端到端 —— 真实 Submission → 独立盲评分 → 落库,按真实 id 出榜带新鲜度。
# =============================================================================
class EndToEndBlindToStore(_OfflinePanel):
    def _tmp_db(self):
        return STORE.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")

    def test_real_submissions_reach_leaderboard_by_true_id(self):
        reg = make_fake_registry()
        meta = _TaskMeta(_t1_spec())
        tr = IF.make_fake_translator()

        subs = [IF.make_fake_submission("vio"),
                IF.make_fake_submission("simular")]
        res = BP.score_submissions(subs, meta, reg, translator=tr, seed=9)

        con = self._tmp_db()
        BP.persist_blind_scores(con, res)

        board = LB.from_store(con, baseline="vio")
        ranked = {r["product"] for r in board["ranking"]}
        # 榜单按 **真实 id** 归位,不是 Product A/B(盲的是身份不是归属)。
        self.assertEqual(ranked, {"vio", "simular"})

        row = con.execute("SELECT competitor_version, tested_at FROM scores "
                          "WHERE product='vio'").fetchone()
        self.assertEqual(row["competitor_version"], "fake-build-2026.07")
        self.assertEqual(row["tested_at"], 1_800_000_000.0)
        con.close()

    def test_cannot_reach_competitor_excluded_not_zero(self):
        reg = make_fake_registry()
        reg.add(Competitor("cloud_only", "CloudOnly",
                            can_operate_local_desktop=False))
        meta = _TaskMeta(_t1_spec())
        tr = IF.make_fake_translator()

        subs = [IF.make_fake_submission("vio"),
                IF.make_fake_submission("cloud_only")]
        res = BP.score_submissions(subs, meta, reg, translator=tr, seed=2)
        cloud = next(b for b in res if b.product == "cloud_only")
        self.assertEqual(cloud.run.gate, "cannot-reach")
        self.assertFalse(cloud.score["scored"])

        con = self._tmp_db()
        BP.persist_blind_scores(con, res)
        board = LB.from_store(con, baseline="vio")
        self.assertTrue(any(e["product"] == "cloud_only"
                            for e in board["excluded"]))
        self.assertFalse(any(r["product"] == "cloud_only"
                             for r in board["ranking"]))
        con.close()


if __name__ == "__main__":
    unittest.main()
