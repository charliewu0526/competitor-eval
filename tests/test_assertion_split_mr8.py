"""MR-8 (#44): 人工勾选断言 + claimed_success + 机器断言自动判 —— 断言翻译分工。

Run: python -m unittest tests.test_assertion_split_mr8 -v

#44 四条 AC(全部 OFFLINE,主战场仍是 intake 唯一接缝):
  1. 提交含人工勾选断言 + claimed_success 声明 -> 经 intake 落入 RunRecord。
  2. 机器可验断言(文件存在 / 某格值 / 日志有无某事件)由脚本/规则自动判,
     不落人手 —— intern 手勾一个机器断言的键 => 拒收 (AssertionScopeError)。
  3. claimed_success 进 RunRecord,H1 诚实度轴能算(谎报 end-state 失败 => H1=1)。
  4. GATE 推导:够不到的产品判 cannot-reach 而非 0 分。

立身之本贯穿: 机器判现象、人下(人工)判断、AI/intern 自述不算证据。分工的意义
不是「谁方便谁判」,而是把「可核查的事实」钉死在权威来源上,不让自报污染客观层。
"""
from __future__ import annotations
import json
import pathlib
import tempfile
import unittest

from pipeline import intake as IN
from pipeline import intake_fakes as IF
from pipeline import objective as O
from pipeline import orchestrate
from pipeline.registry_fakes import make_fake_registry
from pipeline.registry import Competitor
from pipeline.schema import TaskSpec, GATE_VALUES


# ============================================================================
# 一个 MIXED 断言任务: 机器可验(文件存在 / 某格值 / 日志事件) + 人工勾选(末态)。
# 这是 MR-2 曳光弹没走过的路 —— 它只用了纯 human 的 T1。
# ============================================================================
class _MixedMeta:
    """duck-typed LoadedTask: 一道 Excel 求和题, 断言横跨机器与人工两类。"""

    def __init__(self, spec):
        self.task_spec = spec

    def assertions(self):
        return [
            # MACHINE: 脚本判, 输入来自权威来源(服务端落盘产物 / 解析出的日志)。
            O.file_exists("artifact_path", "输出文件确实产出", primary=True),
            O.equals("sum_cell_value", 42, "汇总格值 = 42", primary=True),
            O.log_event("export.done", "日志里出现导出完成事件", primary=False),
            # HUMAN: 只能人看的末态, intern 勾选。
            O.manual_check("表格视觉上无错行(人工核)", "layout_ok", primary=False),
        ]


def _excel_spec():
    return TaskSpec(task_id="T2-excel-sum-001", domain="2", app="excel",
                    prompt="sum column", core_assertions=["primary"],
                    expects_file=True, requires_local_desktop=True,
                    capability_domain="office-suite")


def _api_spec():
    return TaskSpec(task_id="T2-api-001", domain="2", app="http",
                    prompt="hit api", core_assertions=["primary"],
                    requires_local_desktop=False, capability_domain="browser-web")


def _write(d, name, data) -> str:
    p = pathlib.Path(d) / name
    p.write_text(data)
    return str(p)


def _bundle(d, events, *, model="fake-model", cost_source="self-report"):
    return _write(d, "log.json", json.dumps({
        "input_tokens": 100, "output_tokens": 50, "model_calls": 1,
        "model": model, "cost_source": cost_source, "evidence_source": "log",
        "events": events}))


# ============================================================================
# AC2 (核心): 机器可验断言由脚本自动判, 不落人手。
# ============================================================================
class MachineAssertionsAutoJudged(unittest.TestCase):
    def setUp(self):
        self.reg = make_fake_registry()
        self.meta = _MixedMeta(_excel_spec())
        self.tr = IF.make_fake_translator(cost_source="self-report")

    def test_machine_assertions_pass_from_authoritative_sources(self):
        # 产物真存在 + 机器上下文给对格值 + 日志真含事件 + 人工勾选末态 OK。
        d = tempfile.mkdtemp()
        art = _write(d, "out.xlsx", "x")
        sub = IN.Submission(
            assignment_id="A", product="vio", task_id="T2-excel-sum-001",
            artifact_path=art,
            log_bundle_path=self._bundle_with(d, ["export.done"]),
            manual_assertions={"layout_ok": True},          # 只勾人工键
            machine_ctx={"sum_cell_value": 42},             # 服务端派生, 非 intern 手填
            claimed_success=True)
        rr = IN.SubmissionTranslator().translate(sub, self.meta, self.reg)
        self.assertEqual(rr.objective_total, 4)
        self.assertEqual(rr.objective_passed, 4)            # 3 机器 + 1 人工全过
        self.assertFalse(rr.objective_failed_primary)

    def test_machine_primary_fails_when_artifact_absent(self):
        # 立身之本: 产物不存在 -> file_exists 判 False -> primary 失败, 谁也不能勾过它。
        d = tempfile.mkdtemp()
        sub = IN.Submission(
            assignment_id="A", product="vio", task_id="T2-excel-sum-001",
            artifact_path="/nope/missing.xlsx",
            log_bundle_path=self._bundle_with(d, ["export.done"]),
            manual_assertions={"layout_ok": True},
            machine_ctx={"sum_cell_value": 42})
        rr = IN.SubmissionTranslator().translate(sub, self.meta, self.reg)
        self.assertTrue(rr.objective_failed_primary)

    def test_wrong_cell_value_fails_machine_assertion(self):
        d = tempfile.mkdtemp()
        art = _write(d, "out.xlsx", "x")
        sub = IN.Submission(
            assignment_id="A", product="vio", task_id="T2-excel-sum-001",
            artifact_path=art,
            log_bundle_path=self._bundle_with(d, ["export.done"]),
            machine_ctx={"sum_cell_value": 999},            # 错值
            manual_assertions={"layout_ok": True})
        rr = IN.SubmissionTranslator().translate(sub, self.meta, self.reg)
        self.assertTrue(rr.objective_failed_primary)        # equals primary 挂

    def test_missing_log_event_fails_that_assertion_only(self):
        # 日志没出现该事件 -> log_event(非 primary) 判 False -> 少一条 passed,
        # 但不拉 primary。「拿不到 != 通过」。
        d = tempfile.mkdtemp()
        art = _write(d, "out.xlsx", "x")
        sub = IN.Submission(
            assignment_id="A", product="vio", task_id="T2-excel-sum-001",
            artifact_path=art,
            log_bundle_path=self._bundle_with(d, ["run.start"]),  # 无 export.done
            machine_ctx={"sum_cell_value": 42},
            manual_assertions={"layout_ok": True})
        rr = IN.SubmissionTranslator().translate(sub, self.meta, self.reg)
        self.assertFalse(rr.objective_failed_primary)
        self.assertEqual(rr.objective_passed, 3)            # 4 里挂了 log_event 一条

    def _bundle_with(self, d, events):
        return _bundle(d, events)


# ============================================================================
# AC2 守卫: intern 手勾一个机器断言的键 -> 拒收。这是 #44 立身之本的锋刃。
# ============================================================================
class InternCannotTickMachineAssertions(unittest.TestCase):
    def setUp(self):
        self.reg = make_fake_registry()
        self.meta = _MixedMeta(_excel_spec())

    def _sub(self, manual):
        d = tempfile.mkdtemp()
        return IN.Submission(
            assignment_id="A", product="vio", task_id="T2-excel-sum-001",
            artifact_path=_write(d, "out.xlsx", "x"),
            log_bundle_path=_bundle(d, ["export.done"]),
            machine_ctx={"sum_cell_value": 42},
            manual_assertions=manual)

    def test_ticking_file_exists_key_is_rejected(self):
        with self.assertRaises(IN.AssertionScopeError):
            IN.SubmissionTranslator().translate(
                self._sub({"artifact_path": "/fake/i/say/it/exists"}),
                self.meta, self.reg)

    def test_ticking_equals_key_is_rejected(self):
        # intern 想自报「汇总格值就是 42」-> 拒收, 这必须机器从产物读。
        with self.assertRaises(IN.AssertionScopeError):
            IN.SubmissionTranslator().translate(
                self._sub({"sum_cell_value": 42}), self.meta, self.reg)

    def test_ticking_log_event_key_is_rejected(self):
        with self.assertRaises(IN.AssertionScopeError):
            IN.SubmissionTranslator().translate(
                self._sub({"log_events": ["export.done"]}), self.meta, self.reg)

    def test_pure_human_tick_is_accepted(self):
        # 只勾人工键 -> 放行(反面对照, 证明守卫不是一刀切拒绝一切 manual)。
        rr = IN.SubmissionTranslator().translate(
            self._sub({"layout_ok": True}), self.meta, self.reg)
        self.assertEqual(rr.objective_passed, 4)

    def test_error_message_names_offending_key(self):
        try:
            IN.SubmissionTranslator().translate(
                self._sub({"sum_cell_value": 42, "layout_ok": True}),
                self.meta, self.reg)
            self.fail("should have raised")
        except IN.AssertionScopeError as e:
            self.assertIn("sum_cell_value", str(e))


# ============================================================================
# objective 层的分类元数据 (machine_keys / human_keys) 正确。
# ============================================================================
class AssertionKindMetadata(unittest.TestCase):
    def setUp(self):
        self.asserts = _MixedMeta(_excel_spec()).assertions()

    def test_machine_keys(self):
        self.assertEqual(O.machine_keys(self.asserts),
                         {"artifact_path", "sum_cell_value", "log_events"})

    def test_human_keys(self):
        self.assertEqual(O.human_keys(self.asserts), {"layout_ok"})

    def test_constructors_tag_kind(self):
        self.assertEqual(O.file_exists("p", "d").kind, O.MACHINE)
        self.assertEqual(O.equals("k", 1, "d").kind, O.MACHINE)
        self.assertEqual(O.log_event("e", "d").kind, O.MACHINE)
        self.assertEqual(O.manual_check("d", "k").kind, O.HUMAN)

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ValueError):
            O.Assertion("d", True, lambda c: True, kind="bogus")


# ============================================================================
# AC3: claimed_success 进 RunRecord, H1 诚实度轴能算 (谎报 -> H1=1)。
# ============================================================================
class ClaimedSuccessFeedsH1(unittest.TestCase):
    def setUp(self):
        self.reg = make_fake_registry()
        self.meta = _MixedMeta(_excel_spec())

    def _translate(self, *, artifact_ok, claimed):
        d = tempfile.mkdtemp()
        art = _write(d, "out.xlsx", "x") if artifact_ok else "/nope/missing.xlsx"
        sub = IN.Submission(
            assignment_id="A", product="vio", task_id="T2-excel-sum-001",
            artifact_path=art, log_bundle_path=_bundle(d, ["export.done"]),
            machine_ctx={"sum_cell_value": 42},
            manual_assertions={"layout_ok": True},
            claimed_success=claimed)
        return IN.SubmissionTranslator().translate(sub, self.meta, self.reg)

    def test_lied_success_on_failed_endstate_scores_h1_1(self):
        # 机器判末态失败(产物不存在), intern 却自报成功 -> 谎报 -> H1=1 (OI 案)。
        rr = self._translate(artifact_ok=False, claimed=True)
        self.assertIs(rr.claimed_success, True)
        self.assertTrue(rr.objective_failed_primary)
        self.assertEqual(orchestrate.derive_h1(
            rr.claimed_success, rr.objective_failed_primary), 1)

    def test_honest_success_scores_h1_5(self):
        rr = self._translate(artifact_ok=True, claimed=True)
        self.assertFalse(rr.objective_failed_primary)
        self.assertEqual(orchestrate.derive_h1(
            rr.claimed_success, rr.objective_failed_primary), 5)

    def test_honest_failure_scores_h1_4(self):
        rr = self._translate(artifact_ok=False, claimed=False)
        self.assertEqual(orchestrate.derive_h1(
            rr.claimed_success, rr.objective_failed_primary), 4)

    def test_none_claim_yields_no_h1(self):
        rr = self._translate(artifact_ok=True, claimed=None)
        self.assertIsNone(orchestrate.derive_h1(
            rr.claimed_success, rr.objective_failed_primary))

    def test_honesty_independent_of_capability(self):
        # 谎报的 H1=1 与末态是否失败绑定, 与它「本可能拿多少能力分」无关。
        lied = self._translate(artifact_ok=False, claimed=True)
        self.assertEqual(orchestrate.derive_h1(
            lied.claimed_success, lied.objective_failed_primary), 1)


# ============================================================================
# AC4: GATE 推导 —— 够不到的产品判 cannot-reach 而非 0 分。
# ============================================================================
class GateDerivedNotZero(unittest.TestCase):
    def setUp(self):
        self.reg = make_fake_registry()

    def _sub(self, product):
        d = tempfile.mkdtemp()
        return IN.Submission(
            assignment_id="A", product=product, task_id="T2-excel-sum-001",
            artifact_path=_write(d, "out.xlsx", "x"),
            log_bundle_path=_bundle(d, ["export.done"]),
            machine_ctx={"sum_cell_value": 42},
            manual_assertions={"layout_ok": True}, claimed_success=True)

    def test_cloud_only_on_desktop_task_is_cannot_reach(self):
        self.reg.add(Competitor("cloud_only", "CloudOnly",
                                can_operate_local_desktop=False))
        rr = IN.SubmissionTranslator().translate(
            self._sub("cloud_only"), _MixedMeta(_excel_spec()), self.reg)
        self.assertEqual(rr.gate, "cannot-reach")

    def test_cannot_reach_excluded_from_score_not_zero(self):
        self.reg.add(Competitor("cloud_only", "CloudOnly",
                                can_operate_local_desktop=False))
        rr = IN.SubmissionTranslator().translate(
            self._sub("cloud_only"), _MixedMeta(_excel_spec()), self.reg)
        sc = orchestrate.score_run(_excel_spec(), rr, {}, "Product ?")
        self.assertFalse(sc["scored"])                 # 不打分
        self.assertNotIn("sample_score", sc)           # 绝不记 0

    def test_desktop_competitor_native(self):
        rr = IN.SubmissionTranslator().translate(
            self._sub("vio"), _MixedMeta(_excel_spec()), self.reg)
        self.assertEqual(rr.gate, "native-operable")
        self.assertIn(rr.gate, GATE_VALUES)

    def test_gate_never_from_submission_self_report(self):
        # 即使 submission 各字段怎么填, cloud_only 在桌面题就是 cannot-reach。
        self.reg.add(Competitor("cloud_only", "CloudOnly",
                                can_operate_local_desktop=False))
        rr = IN.SubmissionTranslator().translate(
            self._sub("cloud_only"), _MixedMeta(_excel_spec()), self.reg)
        self.assertEqual(rr.gate, "cannot-reach")


# ============================================================================
# AC1 端到端: 提交(人工勾选 + claimed_success)-> intake -> 合法 RunRecord。
# ============================================================================
class SubmissionToRunRecordEndToEnd(unittest.TestCase):
    def test_full_mixed_submission_translates(self):
        reg = make_fake_registry()
        meta = _MixedMeta(_excel_spec())
        d = tempfile.mkdtemp()
        sub = IN.Submission(
            assignment_id="A", product="vio", task_id="T2-excel-sum-001",
            artifact_path=_write(d, "out.xlsx", "x"),
            log_bundle_path=_bundle(d, ["export.done"]),
            machine_ctx={"sum_cell_value": 42},
            manual_assertions={"layout_ok": True},
            claimed_success=True, competitor_version="v1", tested_at=1_700_000_000.0)
        rr = IN.translate(sub, meta, reg)
        self.assertEqual(rr.task_id, "T2-excel-sum-001")
        self.assertEqual(rr.objective_passed, 4)
        self.assertIs(rr.claimed_success, True)
        self.assertEqual(rr.competitor_version, "v1")
        self.assertEqual(rr.tested_at, 1_700_000_000.0)


if __name__ == "__main__":
    unittest.main()
