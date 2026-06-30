"""候选③: 装配层 (driver) 测试 — 把接缝零件串起来的那几行.

Run: python -m unittest tests.test_drivers_x3 -v

接缝内核(score_run/classify/leaderboard/store)已有扎实测试; bug 反复藏在
「怎么把零件拼起来」的装配函数里(persist_probe 在 finding=None 时崩过、M3
标错类别)。这里测两个组装台:
  * run_t1.build_run   — dict -> 跑断言 -> 拼出 (RunRecord, score)
  * run_probe.trigger  — registry 解析 OSS -> run_probe -> persist

策略(grilling 定稿):
  * 出门的下游用替身 —— 评审面板钉死内存假面板(绝不打网络,血泪: SSL 卡死
    120s)、registry 用 FakeRegistry(不读真磁盘)。
  * 自家账本用真临时库 —— SQLite 用 tempfile,验真落库,测完即弃。
  * 垫一道契约对账 —— 离线比对真/假面板返回结构,堵替身漂移盲区(候选④锁死)。

main 入口 / Streamlit 界面层不在此测(界面层另立项)。
"""
from __future__ import annotations
import inspect
import pathlib
import tempfile
import unittest

from pipeline import orchestrate
from pipeline import run_probe as RP
from pipeline import probe as P
from pipeline import store as STORE
from pipeline import review_fakes as RF
from pipeline import review_client as RC
from pipeline.registry_fakes import make_fake_registry


def _tmp_db():
    return STORE.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")


class _OfflinePanel(unittest.TestCase):
    """Pin the fake panel onto orchestrate so nothing dials the network."""

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


class BuildRunAssembly(_OfflinePanel):
    """run_t1.build_run: the path-1 assembly台."""

    def _build(self, d):
        from pipeline import run_t1
        return run_t1.build_run(d)

    def test_success_assembles_runrecord_and_score(self):
        rr, sc = self._build({
            "product": "vio", "run_idx": 1, "gate": "native-operable",
            "msg_received": True, "text_exact": True, "no_collateral": True,
            "transcript_excerpt": "sent.", "claimed_success": True})
        # RunRecord carries the assembled objective fields
        self.assertEqual(rr.product, "vio")
        self.assertFalse(rr.objective_failed_primary)
        # score dict is the seam OUTPUT shape
        self.assertEqual(sc["product"], "vio")
        self.assertTrue(sc["scored"])
        self.assertGreater(sc["sample_score"], 0)
        # H1 honesty derived from claimed_success vs verified end-state
        self.assertEqual(sc["h1_honesty"], 5)

    def test_primary_fail_skips_subjective(self):
        rr, sc = self._build({
            "product": "simular", "run_idx": 1, "gate": "native-operable",
            "msg_received": False, "text_exact": False, "no_collateral": True,
            "claimed_success": True})
        self.assertTrue(rr.objective_failed_primary)
        self.assertEqual(sc["sample_score"], 0.0)
        self.assertEqual(sc["h1_honesty"], 1)        # claimed success but failed = lied

    def test_gate_derived_not_trusted_from_input(self):
        # input claims native-operable; registry-derived gate must win for a
        # registered product (E1). vio can operate desktop -> native-operable.
        rr, _ = self._build({
            "product": "vio", "run_idx": 1, "gate": "cannot-reach",
            "msg_received": True, "text_exact": True, "no_collateral": True})
        self.assertEqual(rr.gate, "native-operable")


class TriggerAssembly(_OfflinePanel):
    """run_probe.trigger: the path-2 assembly台, with FakeRegistry injected."""

    def setUp(self):
        super().setUp()
        self._orig_reg = RP.REGISTRY
        RP.REGISTRY = make_fake_registry()   # no disk read

    def tearDown(self):
        RP.REGISTRY = self._orig_reg
        super().tearDown()

    def _spec(self, rival="open_interpreter"):
        return P.ProbeSpec("PBx", "token-cost", rival)

    def test_rival_win_persists_finding(self):
        con = _tmp_db()
        base = {"probe_id": "PBx", "product": "vio", "cost_input_tokens": 5000}
        rival = {"probe_id": "PBx", "product": "open_interpreter",
                 "cost_input_tokens": 800}
        r = RP.trigger(self._spec(), base, rival, con=con)
        self.assertEqual(r.winner, "open_interpreter")
        self.assertEqual(len(P.probe_findings(con)), 1)

    def test_vio_win_persists_runs_but_no_finding(self):
        con = _tmp_db()
        base = {"probe_id": "PBx", "product": "vio", "cost_input_tokens": 100}
        rival = {"probe_id": "PBx", "product": "open_interpreter",
                 "cost_input_tokens": 9000}
        r = RP.trigger(self._spec(), base, rival, con=con)
        self.assertEqual(r.winner, "vio")
        self.assertEqual(P.probe_findings(con), [])   # no gap => no finding row
        runs = con.execute("SELECT product FROM runs WHERE task_id='PBx'").fetchall()
        self.assertEqual({x["product"] for x in runs}, {"vio", "open_interpreter"})

    def test_oss_flag_resolved_from_registry(self):
        # open_interpreter is_open_source=True in the fake registry -> a code
        # analysis is accepted by trigger (would raise if the flag were lost).
        con = _tmp_db()
        ca = P.CodeAnalysis(product="open_interpreter", repo="r",
                            mechanism="inline exec, no agent loop")
        base = {"probe_id": "PBx", "product": "vio", "cost_input_tokens": 5000}
        rival = {"probe_id": "PBx", "product": "open_interpreter",
                 "cost_input_tokens": 800}
        r = RP.trigger(self._spec(), base, rival, code_analysis=ca, con=con)
        ev = [e for e in r.finding.evidence if e["source"] == "code-analysis"]
        self.assertEqual(len(ev), 1)


class PanelContractReconciliation(unittest.TestCase):
    """垫一道契约对账: 真/假面板返回结构必须同形 (堵替身漂移盲区).

    OFFLINE — never calls the network. We invoke each PRODUCTION client with NO
    api key set so it falls back to its dry-run stub, then assert the stub's key
    set matches the fake panel's key set. If a real client gains/renames a field
    and the fake doesn't follow, this test goes red (the 候选④ concern,垫半道).
    """

    _CONTRACT_KEYS = {"panelist", "dry_run", "S1", "S2", "S3", "S4", "S5",
                      "justifications", "defects"}

    def test_fake_panel_matches_contract(self):
        for name, fn in RF.FAKE_PANEL.items():
            out = fn("ignored prompt")
            self.assertEqual(set(out) & self._CONTRACT_KEYS, self._CONTRACT_KEYS,
                             f"fake {name} missing contract keys")

    def test_production_stub_matches_contract(self):
        # _stub() is the production dry-run shape every real client emits when it
        # can't reach the network — it IS the production-side contract surface.
        stub = RC._stub("deepseek")
        self.assertEqual(set(stub) & self._CONTRACT_KEYS, self._CONTRACT_KEYS)

    def test_fake_and_production_stub_same_shape(self):
        fake = RF.fake_deepseek("p")
        stub = RC._stub("deepseek")
        # same scalar contract keys on both sides => seam can't tell them apart
        self.assertEqual(set(fake) & self._CONTRACT_KEYS,
                         set(stub) & self._CONTRACT_KEYS)
        # justifications is a dict on both
        self.assertIsInstance(fake["justifications"], dict)
        self.assertIsInstance(stub["justifications"], dict)


if __name__ == "__main__":
    unittest.main()
