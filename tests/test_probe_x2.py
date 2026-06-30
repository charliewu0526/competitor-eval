"""X2: capability-probe (path 2) + 开源代码机理分析.

Run: python -m unittest tests.test_probe_x2 -v

Covers acceptance:
  * kind=capability-probe runs through the seam (two RunRecords -> Finding)
  * probe targets ONE 卖点 dimension (token cost) -> Vio-vs-rival winner
  * is_open_source rival can attach 代码机理分析 as a finding evidence field
  * 机理分析 rides as evidence supporting 借鉴/补齐 (machine never fills judgment)
  * probe results land in the SAME SQLite store + are readable for the board
"""
from __future__ import annotations
import tempfile, unittest, pathlib

from pipeline.schema import RunRecord, TaskSpec
from pipeline import probe as P
from pipeline import store as STORE


def _run(product, **kw):
    base = dict(task_id="PB1", product=product, run_idx=1,
                gate="native-operable")
    base.update(kw)
    return RunRecord(**base)


class SpecContract(unittest.TestCase):
    def test_kind_capability_probe_is_valid_taskspec(self):
        ts = TaskSpec(task_id="PB1", domain="1", app="wechat", prompt="p",
                      core_assertions=["x"], kind="capability-probe")
        self.assertEqual(ts.kind, "capability-probe")

    def test_unknown_dimension_rejected(self):
        with self.assertRaises(P.ProbeError):
            P.ProbeSpec("p", "nonsense-dim", "open_interpreter")

    def test_rival_cannot_equal_baseline(self):
        with self.assertRaises(P.ProbeError):
            P.ProbeSpec("p", "token-cost", "vio")


class TokenCostProbe(unittest.TestCase):
    """ONE 卖点 dimension (token 成本): rival cheaper -> rival wins -> feature-gap."""

    def _probe(self):
        base = _run("vio", cost_input_tokens=4000, cost_output_tokens=1000)
        rival = _run("open_interpreter", cost_input_tokens=900,
                     cost_output_tokens=300)
        spec = P.ProbeSpec("PB1-token", "token-cost", "open_interpreter")
        return spec, base, rival

    def test_rival_lower_token_wins(self):
        spec, base, rival = self._probe()
        r = P.run_probe(spec, base, rival)
        self.assertEqual(r.baseline_metric, 5000)
        self.assertEqual(r.rival_metric, 1200)
        self.assertEqual(r.winner, "open_interpreter")
        self.assertEqual(r.finding.suspected_category, "feature-gap")

    def test_baseline_lower_token_wins(self):
        # flip: Vio cheaper -> baseline wins, not a gap
        base = _run("vio", cost_input_tokens=100, cost_output_tokens=50)
        rival = _run("open_interpreter", cost_input_tokens=9000)
        spec = P.ProbeSpec("PB1-token", "token-cost", "open_interpreter")
        r = P.run_probe(spec, base, rival)
        self.assertEqual(r.winner, "vio")

    def test_machine_never_fills_judgment(self):
        spec, base, rival = self._probe()
        r = P.run_probe(spec, base, rival)
        self.assertIsNone(r.finding.product_judgment)
        self.assertIsNone(r.finding.final_category)

    def test_higher_is_better_dimension(self):
        base = _run("vio", objective_passed=1, objective_total=2)   # ratio .5
        rival = _run("open_interpreter", objective_passed=2, objective_total=2)
        spec = P.ProbeSpec("PB1-cap", "capability", "open_interpreter")
        r = P.run_probe(spec, base, rival)
        self.assertEqual(r.winner, "open_interpreter")


class CodeMechanismAnalysis(unittest.TestCase):
    def test_oss_rival_attaches_mechanism_evidence(self):
        base = _run("vio", cost_input_tokens=5000)
        rival = _run("open_interpreter", cost_input_tokens=1000)
        spec = P.ProbeSpec("PB1-token", "token-cost", "open_interpreter")
        ca = P.CodeAnalysis(
            product="open_interpreter",
            repo="https://github.com/OpenInterpreter/open-interpreter",
            mechanism="内联执行代码、无逐步 agent 循环，省去多轮规划 token",
            refs=["interpreter/core/core.py#L120"], analyst="charlie")
        r = P.run_probe(spec, base, rival, code_analysis=ca,
                        rival_is_open_source=True)
        ev = [e for e in r.finding.evidence if e["source"] == "code-analysis"]
        self.assertEqual(len(ev), 1)
        self.assertIn("内联执行", ev[0]["mechanism"])
        self.assertIn("机理", r.finding.phenomenon)

    def test_mechanism_required_nonempty(self):
        with self.assertRaises(P.ProbeError):
            P.CodeAnalysis(product="oi", repo="r", mechanism="   ")

    def test_code_analysis_rejected_for_closed_source(self):
        base = _run("vio", cost_input_tokens=5000)
        rival = _run("simular", cost_input_tokens=1000)
        spec = P.ProbeSpec("PB1-token", "token-cost", "simular")
        ca = P.CodeAnalysis(product="simular", repo="", mechanism="x")
        with self.assertRaises(P.ProbeError):
            P.run_probe(spec, base, rival, code_analysis=ca,
                        rival_is_open_source=False)

    def test_code_analysis_product_must_match_rival(self):
        base = _run("vio", cost_input_tokens=5000)
        rival = _run("open_interpreter", cost_input_tokens=1000)
        spec = P.ProbeSpec("PB1-token", "token-cost", "open_interpreter")
        ca = P.CodeAnalysis(product="someone_else", repo="r", mechanism="x")
        with self.assertRaises(P.ProbeError):
            P.run_probe(spec, base, rival, code_analysis=ca,
                        rival_is_open_source=True)


class SameStoreAndBoard(unittest.TestCase):
    def _db(self):
        d = tempfile.mkdtemp()
        return STORE.connect(pathlib.Path(d) / "t.db")

    def test_probe_lands_in_sqlite_findings(self):
        con = self._db()
        # path-2 RunRecords carry task_id == probe_id (the probe IS the task)
        base = _run("vio", task_id="PB1-token", cost_input_tokens=5000)
        rival = _run("open_interpreter", task_id="PB1-token", cost_input_tokens=1000)
        spec = P.ProbeSpec("PB1-token", "token-cost", "open_interpreter")
        r = P.run_probe(spec, base, rival)
        fid = P.persist_probe(con, spec, base, rival, r)
        self.assertIsInstance(fid, int)
        # readable as a finding (board renders FROM findings table)
        rows = P.probe_findings(con)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rule"], "capability-probe")
        self.assertEqual(rows[0]["subject"], "open_interpreter")
        # runs persisted too (seam input in same store)
        runs = con.execute("SELECT product FROM runs WHERE task_id='PB1-token'").fetchall()
        self.assertEqual({r["product"] for r in runs}, {"vio", "open_interpreter"})

    def test_reclassify_preserves_pm_judgment(self):
        con = self._db()
        base = _run("vio", cost_input_tokens=5000)
        rival = _run("open_interpreter", cost_input_tokens=1000)
        spec = P.ProbeSpec("PB1-token", "token-cost", "open_interpreter")
        r = P.run_probe(spec, base, rival)
        fid = P.persist_probe(con, spec, base, rival, r)
        # PM decides 值得借鉴
        STORE.set_judgment(con, fid, product_judgment="值得借鉴",
                           final_category="experience-borrow")
        # re-run the probe (machine) — must NOT clobber the human judgment
        P.persist_probe(con, spec, base, rival, P.run_probe(spec, base, rival))
        row = P.probe_findings(con)[0]
        self.assertEqual(row["product_judgment"], "值得借鉴")
        self.assertEqual(row["final_category"], "experience-borrow")


if __name__ == "__main__":
    unittest.main()
