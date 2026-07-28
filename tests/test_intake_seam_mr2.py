"""MR-2 (#38): the intake seam — Submission → RunRecord tracer bullet.

Run: python -m unittest tests.test_intake_seam_mr2 -v

Acceptance (issue #38), all OFFLINE:
  - intake.translate maps a fixed fake Submission into a legal RunRecord
  - production translator + in-memory fake honor the SAME contract
  - GATE is DERIVED via gate_for(competitor, task), NOT trusted from submission
  - machine + human objective assertions both land; cost from parsed log facts;
    claimed_success feeds H1; competitor_version/tested_at carried (ADR-0017)
  - 拿不到日志 -> cost/evidence unavailable, never a fake 0-cost success
  - end-to-end (仿 test_suite_x6 / test_drivers_x3): Submission → translate →
    score_run → store → leaderboard shows the score WITH version + tested_at
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
from pipeline import store as STORE
from pipeline import leaderboard as LB
from pipeline import review_fakes as RF
from pipeline.registry_fakes import make_fake_registry
from pipeline.schema import RunRecord, GATE_VALUES, TaskSpec, COST_SOURCE_VALUES


# The RunRecord fields the seam must fully populate (the contract surface).
CONTRACT_FIELDS = {"task_id", "product", "run_idx", "gate", "objective_passed",
                   "objective_total", "objective_failed_primary", "cost_source",
                   "evidence_source", "claimed_success", "competitor_version",
                   "tested_at"}


class _TaskMeta:
    """Duck-typed suite.LoadedTask stand-in: a TaskSpec + assertions callable.

    Mirrors T1's three manual_check assertions so the tracer bullet exercises
    the human-ticked objective path without touching the real task bank.
    """

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


def _api_spec():
    # a task NOT requiring local desktop -> a desktop-only competitor still
    # participates as api-or-integration (cross-layer), not cannot-reach.
    return TaskSpec(task_id="T2-api-001", domain="2", app="http",
                    prompt="hit an api", core_assertions=["primary"],
                    requires_local_desktop=False,
                    capability_domain="browser-web")


# =============================================================================
# The fake translator maps a fixed Submission -> a legal RunRecord.
# =============================================================================
class FakeTranslatorMapsSubmission(unittest.TestCase):
    def setUp(self):
        self.reg = make_fake_registry()
        self.meta = _TaskMeta(_t1_spec())
        self.tr = IF.make_fake_translator()

    def test_produces_legal_runrecord(self):
        sub = IF.make_fake_submission("vio")
        rr = self.tr.translate(sub, self.meta, self.reg)
        self.assertIsInstance(rr, RunRecord)
        self.assertEqual(rr.task_id, "T1-wechat-send-001")
        self.assertEqual(rr.product, "vio")
        self.assertIn(rr.gate, GATE_VALUES)

    def test_human_ticked_assertions_land(self):
        sub = IF.make_fake_submission("vio")   # all three ticked True
        rr = self.tr.translate(sub, self.meta, self.reg)
        self.assertEqual(rr.objective_total, 3)
        self.assertEqual(rr.objective_passed, 3)
        self.assertFalse(rr.objective_failed_primary)

    def test_primary_fail_flows_through(self):
        sub = IF.make_fake_submission("vio", msg_received=False)
        rr = self.tr.translate(sub, self.meta, self.reg)
        self.assertTrue(rr.objective_failed_primary)

    def test_claimed_success_carried_for_h1(self):
        sub = IF.make_fake_submission("vio", claimed_success=True)
        rr = self.tr.translate(sub, self.meta, self.reg)
        self.assertIs(rr.claimed_success, True)

    def test_freshness_fields_carried(self):
        sub = IF.make_fake_submission("vio")
        rr = self.tr.translate(sub, self.meta, self.reg)
        self.assertEqual(rr.competitor_version, "fake-build-2026.07")
        self.assertEqual(rr.tested_at, 1_800_000_000.0)

    def test_cost_from_parsed_log_facts(self):
        sub = IF.make_fake_submission("vio")
        rr = self.tr.translate(sub, self.meta, self.reg)
        self.assertEqual(rr.cost_input_tokens, 1000)
        self.assertEqual(rr.cost_source, "self-report")
        self.assertEqual(rr.evidence_source, "log")
        self.assertEqual(rr.cost_usd, 0.001)


# =============================================================================
# GATE is DERIVED, never trusted from the submission.
# =============================================================================
class GateDerivedNotSelfReported(unittest.TestCase):
    def setUp(self):
        self.reg = make_fake_registry()
        self.tr = IF.make_fake_translator()

    def test_desktop_task_desktop_competitor_native(self):
        rr = self.tr.translate(IF.make_fake_submission("vio"),
                               _TaskMeta(_t1_spec()), self.reg)
        self.assertEqual(rr.gate, "native-operable")

    def test_desktop_task_unreachable_competitor_cannot_reach(self):
        # inject a cloud-only competitor: can_operate_local_desktop=False on a
        # requires_local_desktop task -> cannot-reach (no unfair 0), regardless
        # of anything the submission might claim.
        from pipeline.registry import Competitor
        self.reg.add(Competitor("cloud_only", "CloudOnly",
                                 can_operate_local_desktop=False))
        rr = self.tr.translate(IF.make_fake_submission("cloud_only"),
                               _TaskMeta(_t1_spec()), self.reg)
        self.assertEqual(rr.gate, "cannot-reach")

    def test_api_task_desktop_competitor_still_native(self):
        rr = self.tr.translate(IF.make_fake_submission("vio", task_id="T2-api-001"),
                               _TaskMeta(_api_spec()), self.reg)
        self.assertEqual(rr.gate, "native-operable")

    def test_unregistered_product_refused(self):
        sub = IF.make_fake_submission("ghost_product")
        with self.assertRaises(ValueError):
            self.tr.translate(sub, _TaskMeta(_t1_spec()), self.reg)


# =============================================================================
# 拿不到日志 -> unavailable, never faked as a 0-cost success.
# =============================================================================
class UnavailableLogNeverFaked(unittest.TestCase):
    def test_unavailable_bundle_yields_unavailable_cost(self):
        reg = make_fake_registry()
        tr = IF.make_fake_translator(cost_source="unavailable")
        rr = tr.translate(IF.make_fake_submission("vio"), _TaskMeta(_t1_spec()), reg)
        self.assertEqual(rr.cost_source, "unavailable")
        self.assertIsNone(rr.cost_usd)
        self.assertEqual(rr.evidence_source, "unavailable")
        self.assertIn(rr.cost_source, COST_SOURCE_VALUES)


# =============================================================================
# Production translator: real disk parse + real price table, same contract.
# =============================================================================
class ProductionTranslatorContract(unittest.TestCase):
    def setUp(self):
        self.reg = make_fake_registry()
        self.meta = _TaskMeta(_t1_spec())

    def _write_bundle(self, d, facts):
        p = pathlib.Path(d) / "log_bundle.json"
        p.write_text(json.dumps(facts))
        return str(p)

    def test_parses_real_bundle_off_disk(self):
        d = tempfile.mkdtemp()
        bundle = self._write_bundle(d, {
            "input_tokens": 2000, "output_tokens": 800, "model_calls": 3,
            "model": "deepseek-v4-pro", "cost_source": "self-report",
            "evidence_source": "log", "events": ["start", "step", "end"]})
        sub = IN.Submission(
            assignment_id="A1", product="vio", task_id="T1-wechat-send-001",
            log_bundle_path=bundle,
            manual_assertions={"msg_received": True, "text_exact": True,
                               "no_collateral": True},
            claimed_success=True, competitor_version="v1", tested_at=1_700_000_000.0)
        rr = IN.SubmissionTranslator().translate(sub, self.meta, self.reg)
        self.assertEqual(rr.cost_input_tokens, 2000)
        self.assertEqual(rr.cost_model_calls, 3)
        self.assertEqual(rr.evidence_source, "log")
        self.assertEqual(rr.gate, "native-operable")
        self.assertEqual(rr.objective_passed, 3)

    def test_missing_bundle_is_unavailable_not_zero_success(self):
        sub = IN.Submission(assignment_id="A1", product="vio",
                            task_id="T1-wechat-send-001",
                            log_bundle_path="/nope/does-not-exist.json",
                            manual_assertions={"msg_received": True,
                                               "text_exact": True,
                                               "no_collateral": True})
        rr = IN.SubmissionTranslator().translate(sub, self.meta, self.reg)
        self.assertEqual(rr.cost_source, "unavailable")
        self.assertIsNone(rr.cost_usd)

    def test_none_valued_tokens_coerced_not_crash(self):
        # 回归 #8: 诚实的 "unavailable" 日志显式带 input_tokens=None(键存在但值 None)。
        # 曾因 int(raw.get("input_tokens", 0)) 在键存在时不取默认 -> int(None) 崩。
        # 现在 None/缺失/空串统一归 0,「拿不到」由 cost_source=unavailable 承载。
        d = tempfile.mkdtemp()
        bundle = self._write_bundle(d, {
            "input_tokens": None, "output_tokens": None, "model_calls": None,
            "model": None, "cost_source": "unavailable",
            "evidence_source": "log", "events": ["native op"]})
        sub = IN.Submission(
            assignment_id="A1", product="vio", task_id="T1-wechat-send-001",
            log_bundle_path=bundle,
            manual_assertions={"msg_received": True, "text_exact": True,
                               "no_collateral": True})
        rr = IN.SubmissionTranslator().translate(sub, self.meta, self.reg)
        self.assertEqual(rr.cost_input_tokens, 0)
        self.assertEqual(rr.cost_output_tokens, 0)
        self.assertEqual(rr.cost_model_calls, 0)
        self.assertEqual(rr.cost_source, "unavailable")

    def test_module_level_translate_signature(self):
        # AC: translate(submission, task_meta, registry) -> RunRecord exists.
        d = tempfile.mkdtemp()
        bundle = self._write_bundle(d, {"input_tokens": 10, "model": None,
                                        "cost_source": "self-report"})
        sub = IN.Submission(assignment_id="A1", product="vio",
                            task_id="T1-wechat-send-001", log_bundle_path=bundle,
                            manual_assertions={"msg_received": True,
                                               "text_exact": True,
                                               "no_collateral": True})
        rr = IN.translate(sub, self.meta, self.reg)
        self.assertIsInstance(rr, RunRecord)


# =============================================================================
# 真/假实现契约对账: both translators fill the SAME RunRecord field surface.
# =============================================================================
class RealVsFakeContract(unittest.TestCase):
    def test_both_impls_fill_contract_fields_identically(self):
        reg = make_fake_registry()
        meta = _TaskMeta(_t1_spec())

        d = tempfile.mkdtemp()
        bundle = pathlib.Path(d) / "b.json"
        bundle.write_text(json.dumps({
            "input_tokens": 1000, "output_tokens": 500, "model_calls": 1,
            "model": "fake-model", "cost_source": "self-report",
            "evidence_source": "log"}))
        prod_sub = IN.Submission(
            assignment_id="A", product="vio", task_id="T1-wechat-send-001",
            log_bundle_path=str(bundle),
            manual_assertions={"msg_received": True, "text_exact": True,
                               "no_collateral": True},
            claimed_success=True, competitor_version="fake-build-2026.07",
            tested_at=1_800_000_000.0)
        prod_rr = IN.SubmissionTranslator().translate(prod_sub, meta, reg)

        fake_rr = IF.make_fake_translator().translate(
            IF.make_fake_submission("vio"), meta, reg)

        for f in CONTRACT_FIELDS:
            self.assertEqual(getattr(prod_rr, f), getattr(fake_rr, f),
                             f"real vs fake diverged on {f}")


# =============================================================================
# END-TO-END: Submission -> translate -> score -> store -> leaderboard.
# The whole point of the tracer bullet (#38 AC #2 & #3).
# =============================================================================
class _OfflinePanel(unittest.TestCase):
    """Pin the fake review panel so score_run never dials the network."""

    def setUp(self):
        self._orig_panel = orchestrate.PANELISTS
        self._saved = {}
        for n, fn in RF.FAKE_PANEL.items():
            self._saved[n] = getattr(orchestrate, n, None)
            setattr(orchestrate, n, fn)
        orchestrate.PANELISTS = tuple(RF.FAKE_PANEL.keys())

    def tearDown(self):
        orchestrate.PANELISTS = self._orig_panel
        for n, v in self._saved.items():
            if v is None:
                if hasattr(orchestrate, n):
                    delattr(orchestrate, n)
            else:
                setattr(orchestrate, n, v)


class EndToEndTracerBullet(_OfflinePanel):
    def _tmp_db(self):
        return STORE.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")

    def test_submission_reaches_leaderboard_with_freshness(self):
        reg = make_fake_registry()
        meta = _TaskMeta(_t1_spec())
        tr = IF.make_fake_translator()

        # 1. fixed Submission -> RunRecord (the ONLY new seam)
        rr = tr.translate(IF.make_fake_submission("vio"), meta, reg)

        # 2. RunRecord -> independent score (the UNTOUCHED scoring core)
        blind = reg.blind_label("vio")
        sc = orchestrate.score_run(meta.task_spec, rr,
                                   {"artifact_summary": "sent"}, blind)
        # carry freshness onto the score row (ADR-0017)
        sc["competitor_version"] = rr.competitor_version
        sc["tested_at"] = rr.tested_at

        # 3. persist to a real temp store
        con = self._tmp_db()
        STORE.upsert_run(con, rr)
        STORE.upsert_score(con, sc)

        # 4. leaderboard finds the score WITH version + tested_at
        board = LB.from_store(con, baseline="vio")
        vio = next(r for r in board["ranking"] if r["product"] == "vio")
        self.assertGreater(vio["avg_capability"], 0)

        row = con.execute("SELECT competitor_version, tested_at FROM scores "
                          "WHERE product='vio'").fetchone()
        self.assertEqual(row["competitor_version"], "fake-build-2026.07")
        self.assertEqual(row["tested_at"], 1_800_000_000.0)
        con.close()

    def test_cannot_reach_competitor_excluded_not_zero(self):
        # A cloud-only competitor on a desktop task must be excluded from the
        # fair board (cannot-reach), never recorded as an unfair 0.
        from pipeline.registry import Competitor
        reg = make_fake_registry()
        reg.add(Competitor("cloud_only", "CloudOnly",
                            can_operate_local_desktop=False))
        meta = _TaskMeta(_t1_spec())
        tr = IF.make_fake_translator()

        rr = tr.translate(IF.make_fake_submission("cloud_only"), meta, reg)
        self.assertEqual(rr.gate, "cannot-reach")
        sc = orchestrate.score_run(meta.task_spec, rr, {}, "Product ?")
        self.assertFalse(sc["scored"])

        con = self._tmp_db()
        STORE.upsert_run(con, rr)
        STORE.upsert_score(con, sc)
        board = LB.from_store(con, baseline="vio")
        self.assertTrue(any(e["product"] == "cloud_only"
                            for e in board["excluded"]))
        self.assertFalse(any(r["product"] == "cloud_only"
                             for r in board["ranking"]))
        con.close()


if __name__ == "__main__":
    unittest.main()
