"""MR-9 (#45): 日志包解析 → cost + 脱敏/原始双视图.

Run: python -m unittest tests.test_logview_mr9 -v

Acceptance (issue #45), all OFFLINE:
  - AC1 无日志包时提交被拒(强制)—— submissions.LogBundleMissing
  - AC2 日志解析出 token/调用/时间线并填 cost_source(非 0 伪装)
  - AC3 同一日志派生 redacted 与 raw 两视图,数据结构就位
  - AC4 脱敏版不含品牌/模型指纹(洗漏=破盲,重点回归)

立身之本回归:脱敏只抹「身份指纹」(品牌 / 模型名),绝不篡改「花了多少 /
是否完成」这类事实数值 —— 那归 raw 视图与客观层。
"""
from __future__ import annotations
import json
import pathlib
import tempfile
import unittest

from pipeline import submissions as SUB
from pipeline import store as STORE
from pipeline import intake as IN
from pipeline import logview as LV
from pipeline.registry_fakes import make_fake_registry
from pipeline.registry import Competitor


def _tmp_db():
    return STORE.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")


def _seed_assignment(con, *, products=("vio", "simular"), status="claimed",
                     claimed_by="u-intern-1"):
    aid = "ASG-mr9-001"
    STORE.upsert_assignment(con, {
        "id": aid, "task_id": "T1-wechat-send-001",
        "products": list(products), "status": status,
        "claimed_by": claimed_by if status != "open" else None,
        "claimed_ts": 1_800_000_000.0 if status != "open" else None,
        "created_ts": 1_800_000_000.0})
    return aid


# =============================================================================
# AC1: 无日志包时提交被拒(强制)
# =============================================================================
class LogBundleMandatory(unittest.TestCase):
    def setUp(self):
        self.con = _tmp_db()
        self.aid = _seed_assignment(self.con)

    def test_no_log_bundle_rejected(self):
        with self.assertRaises(SUB.LogBundleMissing):
            SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                               artifact_path="/u/vio.png", log_bundle_path=None,
                               submitted_by="u-intern-1")

    def test_blank_log_bundle_rejected(self):
        with self.assertRaises(SUB.LogBundleMissing):
            SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                               artifact_path="/u/vio.png", log_bundle_path="   ",
                               submitted_by="u-intern-1")

    def test_rejected_log_bundle_not_persisted(self):
        try:
            SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                               artifact_path="/u/vio.png", log_bundle_path=None,
                               submitted_by="u-intern-1")
        except SUB.LogBundleMissing:
            pass
        self.assertEqual(STORE.submissions_for(self.con, self.aid), [])

    def test_artifact_missing_takes_priority(self):
        # 原始产物守卫在日志包之前: 两者都缺 -> 先报 EvidenceMissing(fail fast 顺序)。
        with self.assertRaises(SUB.EvidenceMissing):
            SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                               artifact_path=None, log_bundle_path=None,
                               submitted_by="u-intern-1")

    def test_bundle_present_passes_guard(self):
        # 交了包(文件路径非空)即过 AC1 强制关 —— 包内解析拿不到是 intake 的事(AC2)。
        row = SUB.submit_product(
            self.con, assignment_id=self.aid, product="vio",
            artifact_path="/u/vio.png",
            log_bundle_path="/uploads/ASG/vio/log_bundle/log.json",
            submitted_by="u-intern-1")
        self.assertEqual(row["log_bundle_path"],
                         "/uploads/ASG/vio/log_bundle/log.json")


# =============================================================================
# AC2: 日志解析出 token/调用/时间线并填 cost_source(非 0 伪装)
# =============================================================================
def _write_bundle(facts: dict) -> str:
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "log_bundle.json"
    p.write_text(json.dumps(facts))
    return str(p)


class LogParseFillsCost(unittest.TestCase):
    def setUp(self):
        self.parser = IN.LogBundleParser()

    def test_parses_tokens_calls_timeline(self):
        path = _write_bundle({
            "input_tokens": 2000, "output_tokens": 800, "model_calls": 3,
            "model": "deepseek-v4-pro", "cost_source": "self-report",
            "evidence_source": "log",
            "timeline": ["run.start", "model.call", "run.end"]})
        facts = self.parser.parse(path)
        self.assertEqual(facts["cost_input_tokens"], 2000)
        self.assertEqual(facts["cost_output_tokens"], 800)
        self.assertEqual(facts["cost_model_calls"], 3)
        self.assertEqual(facts["cost_source"], "self-report")
        # timeline 别名归一到 events(时间线就位)
        self.assertEqual(facts["events"], ["run.start", "model.call", "run.end"])

    def test_missing_bundle_is_unavailable_not_fake_zero(self):
        # 拿不到日志 -> cost_source=unavailable, 绝不伪装成 0-cost 成功。
        facts = self.parser.parse("/nope/missing.json")
        self.assertEqual(facts["cost_source"], "unavailable")
        self.assertEqual(facts["evidence_source"], "unavailable")
        self.assertEqual(facts["events"], [])

    def test_unavailable_source_kept_honest(self):
        # 黑箱竞品: 交了包但 source 自标 unavailable -> 如实透传, 不折算假成本。
        path = _write_bundle({
            "input_tokens": 0, "output_tokens": 0, "model_calls": 0,
            "model": None, "cost_source": "unavailable",
            "evidence_source": "unavailable", "events": []})
        facts = self.parser.parse(path)
        self.assertEqual(facts["cost_source"], "unavailable")


# =============================================================================
# AC3: 同一日志派生 redacted 与 raw 两视图,数据结构就位
# =============================================================================
class TwoViewsDerived(unittest.TestCase):
    def _facts(self):
        return {
            "cost_input_tokens": 1500, "cost_output_tokens": 600,
            "cost_model_calls": 2, "model": "claude-opus-4-8",
            "cost_source": "self-report", "evidence_source": "log",
            "events": ["run.start", "used claude-opus-4-8", "run.end"]}

    def test_returns_both_views(self):
        views = LV.derive_views(self._facts(), registry=make_fake_registry())
        self.assertIsInstance(views, LV.LogViews)
        self.assertIsInstance(views.raw, dict)
        self.assertIsInstance(views.redacted, dict)

    def test_raw_keeps_full_facts(self):
        views = LV.derive_views(self._facts(), registry=make_fake_registry())
        self.assertEqual(views.raw["model"], "claude-opus-4-8")
        self.assertEqual(views.raw["cost_input_tokens"], 1500)
        self.assertEqual(views.raw["events"][1], "used claude-opus-4-8")

    def test_cost_facts_identical_in_both_views(self):
        # 成本数值是事实, 两视图必须一致(脱敏不改事实)。
        views = LV.derive_views(self._facts(), registry=make_fake_registry())
        for k in ("cost_input_tokens", "cost_output_tokens",
                  "cost_model_calls", "cost_source", "evidence_source"):
            self.assertEqual(views.raw[k], views.redacted[k],
                             f"脱敏篡改了事实字段 {k}")

    def test_intake_log_views_entrypoint(self):
        # intake.log_views(submission) 从磁盘包派生双视图(生产入口)。
        path = _write_bundle({
            "input_tokens": 100, "output_tokens": 50, "model_calls": 1,
            "model": "glm-5.2", "cost_source": "self-report",
            "evidence_source": "log", "events": ["ran on glm-5.2"]})
        sub = IN.Submission(assignment_id="A", product="vio",
                            task_id="T1", log_bundle_path=path)
        views = IN.log_views(sub)
        self.assertEqual(views.raw["model"], "glm-5.2")
        self.assertNotIn("glm-5.2", json.dumps(views.redacted, ensure_ascii=False))


# =============================================================================
# AC4: 脱敏版不含品牌/模型指纹(洗漏=破盲,重点回归)
# =============================================================================
class RedactionScrubsFingerprints(unittest.TestCase):
    """高风险回归: 脱敏版一旦漏了品牌 / 模型指纹, 盲评就被泄底破盲。"""

    def _facts_with_fingerprints(self):
        # 品牌指纹(Violoop / Simular / Open Interpreter)+ 模型指纹(deepseek-v4-pro)
        # 埋进事件时间线 + model 字段。
        return {
            "cost_input_tokens": 1000, "cost_output_tokens": 500,
            "cost_model_calls": 1, "model": "deepseek-v4-pro",
            "cost_source": "self-report", "evidence_source": "log",
            "events": [
                "Violoop agent started the run",
                "called model deepseek-v4-pro",
                "Simular fallback considered",
                "Open Interpreter compat shim loaded",
                "run.end",
            ]}

    def _redacted_blob(self, registry=None, price_table=None):
        from pipeline.cost_client import PriceTable
        pt = price_table or PriceTable.load()
        reg = registry or make_fake_registry()
        views = LV.derive_views(self._facts_with_fingerprints(),
                                registry=reg, price_table=pt)
        return json.dumps(views.redacted, ensure_ascii=False), views

    def test_brand_names_scrubbed_from_redacted(self):
        blob, _ = self._redacted_blob()
        for brand in ("Violoop", "Simular", "Open Interpreter", "vio", "simular"):
            self.assertNotIn(brand, blob,
                             f"脱敏漏了品牌指纹 {brand!r} —— 破盲高风险回归")

    def test_model_names_scrubbed_from_redacted(self):
        blob, views = self._redacted_blob()
        # model 字段被抹成占位符(不是 unavailable —— 是「有但盲掉」)。
        self.assertEqual(views.redacted["model"], LV.REDACTED_MODEL)
        self.assertNotIn("deepseek-v4-pro", blob,
                         "脱敏漏了模型指纹 —— 破盲高风险回归")

    def test_raw_still_has_fingerprints(self):
        # raw 视图给成本统计 + 人工抽查用, 指纹必须原样保留(对照组)。
        _, views = self._redacted_blob()
        raw = json.dumps(views.raw, ensure_ascii=False)
        self.assertIn("Violoop", raw)
        self.assertIn("deepseek-v4-pro", raw)

    def test_new_competitor_scrubbed_without_code_change(self):
        # 加竞品 = 改数据(registry)不改脱敏代码: 新竞品品牌也被自动洗掉。
        reg = make_fake_registry()
        reg.add(Competitor("kimi_secret_brand", "KimiSecretBrand",
                            can_operate_local_desktop=False))
        facts = self._facts_with_fingerprints()
        facts["events"] = facts["events"] + ["KimiSecretBrand joined"]
        views = LV.derive_views(facts, registry=reg)
        blob = json.dumps(views.redacted, ensure_ascii=False)
        self.assertNotIn("KimiSecretBrand", blob)

    def test_off_table_model_still_scrubbed(self):
        # 闭源竞品用价表里没有的模型: 本包实际 model 名也纳入指纹, 照样洗。
        facts = self._facts_with_fingerprints()
        facts["model"] = "secret-closed-model-x1"
        facts["events"] = ["ran on secret-closed-model-x1"]
        views = LV.derive_views(facts, registry=make_fake_registry())
        blob = json.dumps(views.redacted, ensure_ascii=False)
        self.assertNotIn("secret-closed-model-x1", blob)

    def test_redactor_case_insensitive_and_longest_first(self):
        # 大小写不敏感 + 长词优先(防「Open Interpreter」被切成半截指纹残留)。
        r = LV.Redactor(["Open Interpreter", "Open"])
        out = r.redact_text("used OPEN INTERPRETER and open source")
        self.assertNotIn("Interpreter", out)
        self.assertNotIn("INTERPRETER", out)

    def test_numeric_facts_survive_redaction(self):
        # 脱敏只抹字符串指纹, token/calls 等数值事实不被误伤。
        _, views = self._redacted_blob()
        self.assertEqual(views.redacted["cost_input_tokens"], 1000)
        self.assertEqual(views.redacted["cost_model_calls"], 1)


if __name__ == "__main__":
    unittest.main()
