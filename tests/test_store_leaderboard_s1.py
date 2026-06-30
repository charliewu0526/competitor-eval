"""S1: SQLite store + leaderboard + PM write-back.

Run: python -m unittest tests.test_store_leaderboard_s1 -v

Acceptance (issue #S1):
  - runs/scores/findings tables write & read
  - leaderboard(baseline, rivals[]) -> ranking + per-task matrix + honesty column
  - cannot-reach competitor NOT in ranking (aligns with E1)
  - finding 产品判断/最终分类 editable -> writes back to SQLite
  - honesty is an INDEPENDENT column, not folded into capability
"""
from __future__ import annotations
import tempfile
import pathlib
import unittest
from pipeline import store, leaderboard as LB, findings as F
from pipeline.schema import RunRecord


def _tmpdb():
    d = tempfile.mkdtemp()
    return str(pathlib.Path(d) / "t.db")


def _score(task, product, *, gate="native-operable", sample=None,
           h1=None, scored=True, reason=None, run_idx=1):
    return {"task_id": task, "product": product, "run_idx": run_idx,
            "gate": gate, "scored": scored, "reason": reason,
            "objective_ratio": 1.0, "sample_score": sample, "h1_honesty": h1,
            "subjective": {"S1": 4}, "disagreement_flagged": [], "defects": []}


class StoreRoundTrip(unittest.TestCase):
    def test_runs_scores_findings_write_read(self):
        con = store.connect(_tmpdb())
        rr = RunRecord(task_id="T1", product="vio", run_idx=1,
                       gate="native-operable", objective_passed=3,
                       objective_total=3, claimed_success=True,
                       evidence_source="screenshot")
        store.upsert_run(con, rr)
        store.upsert_score(con, _score("T1", "vio", sample=0.9, h1=5))
        f = F.Finding(task_id="T1", rule="vio-bug",
                      suspected_category="suspected-bug", subject="vio",
                      phenomenon="failed", evidence=[{"source": "log"}])
        fid = store.upsert_finding(con, f)
        self.assertIsInstance(fid, int)
        self.assertEqual(len(con.execute("SELECT * FROM runs").fetchall()), 1)
        scs = store.all_scores(con)
        self.assertEqual(scs[0]["sample_score"], 0.9)
        self.assertEqual(scs[0]["h1_honesty"], 5)
        self.assertEqual(len(store.all_findings(con)), 1)

    def test_upsert_is_idempotent(self):
        con = store.connect(_tmpdb())
        store.upsert_score(con, _score("T1", "vio", sample=0.5))
        store.upsert_score(con, _score("T1", "vio", sample=0.9))  # same key
        scs = store.all_scores(con)
        self.assertEqual(len(scs), 1)             # updated, not duplicated
        self.assertEqual(scs[0]["sample_score"], 0.9)


class SchemaMigration(unittest.TestCase):
    """A DB created before A3's cost_* columns must auto-migrate on connect()."""

    def _legacy_runs_ddl(self):
        # an old runs table: no cost_input/output_tokens / cost_model_calls
        return ("CREATE TABLE runs (task_id TEXT NOT NULL, product TEXT NOT NULL, "
                "run_idx INTEGER NOT NULL, gate TEXT NOT NULL, "
                "evidence_source TEXT DEFAULT 'unavailable', cost_usd REAL, "
                "cost_source TEXT DEFAULT 'unavailable', ts REAL, "
                "PRIMARY KEY (task_id, product, run_idx))")

    def test_missing_columns_backfilled(self):
        import sqlite3
        path = _tmpdb()
        raw = sqlite3.connect(path)
        raw.execute(self._legacy_runs_ddl())
        raw.execute("INSERT INTO runs (task_id, product, run_idx, gate) "
                    "VALUES ('T1','vio',1,'native-operable')")
        raw.commit(); raw.close()
        # connect() must ALTER the missing cost_* columns in
        con = store.connect(path)
        cols = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
        for c in ("cost_input_tokens", "cost_output_tokens", "cost_model_calls",
                  "claimed_success", "objective_passed", "transcript_excerpt"):
            self.assertIn(c, cols, f"{c} not back-filled")
        # the pre-existing row survives and an upsert with new cols now works
        rr = RunRecord(task_id="T1", product="vio", run_idx=1,
                       gate="native-operable", cost_input_tokens=120,
                       cost_model_calls=2)
        store.upsert_run(con, rr)
        row = con.execute("SELECT cost_input_tokens FROM runs "
                          "WHERE product='vio'").fetchone()
        self.assertEqual(row[0], 120)

    def test_migrate_idempotent(self):
        con = store.connect(_tmpdb())          # fresh DB, full schema
        self.assertEqual(store._migrate(con), [])  # nothing to add second time


class LeaderboardRanking(unittest.TestCase):
    def test_ranking_and_matrix(self):
        scores = [
            _score("T1", "vio", sample=0.9, h1=5),
            _score("T1", "simular", sample=0.6, h1=4),
            _score("T1", "open_interpreter", sample=0.3, h1=1),
        ]
        lb = LB.leaderboard("vio", scores)
        self.assertEqual([r["product"] for r in lb["ranking"]],
                         ["vio", "simular", "open_interpreter"])
        self.assertEqual(lb["ranking"][0]["rank"], 1)
        self.assertTrue(lb["ranking"][0]["is_baseline"])
        # per-task matrix populated
        self.assertEqual(lb["matrix"]["simular"]["T1"]["sample_score"], 0.6)
        self.assertEqual(lb["tasks"], ["T1"])
        # vs_baseline computed
        oi = next(r for r in lb["ranking"] if r["product"] == "open_interpreter")
        self.assertEqual(oi["vs_baseline"], round(0.3 - 0.9, 4))

    def test_cannot_reach_excluded_from_ranking(self):
        scores = [
            _score("T1", "vio", sample=0.9, h1=5),
            _score("T1", "cloud_agent", gate="cannot-reach", sample=None,
                   scored=False, reason="cannot-reach"),
        ]
        lb = LB.leaderboard("vio", scores)
        prods = [r["product"] for r in lb["ranking"]]
        self.assertNotIn("cloud_agent", prods)        # E1 alignment
        self.assertEqual(len(lb["excluded"]), 1)
        self.assertEqual(lb["excluded"][0]["product"], "cloud_agent")

    def test_honesty_is_independent_column(self):
        # 危险的强: high capability, low honesty. 可信的弱: low cap, high honesty.
        scores = [
            _score("T1", "danger", sample=0.95, h1=1),
            _score("T1", "trusty", sample=0.30, h1=5),
        ]
        lb = LB.leaderboard("vio", scores)
        ranking = {r["product"]: r for r in lb["ranking"]}
        # ranked by capability -> danger first
        self.assertEqual(lb["ranking"][0]["product"], "danger")
        # but honesty travels separately and is NOT mixed in
        self.assertEqual(ranking["danger"]["honesty_avg"], 1.0)
        self.assertEqual(ranking["trusty"]["honesty_avg"], 5.0)


class PMWriteBack(unittest.TestCase):
    def test_set_judgment_writes_back(self):
        con = store.connect(_tmpdb())
        f = F.Finding(task_id="T1", rule="feature-gap",
                      suspected_category="feature-gap", subject="simular",
                      phenomenon="competitor ahead", evidence=[{"source": "log"}])
        fid = store.upsert_finding(con, f)
        # machine left these empty
        row = store.all_findings(con)[0]
        self.assertIsNone(row["product_judgment"])
        self.assertIsNone(row["final_category"])
        # PM edits via the board
        store.set_judgment(con, fid, product_judgment="必须补齐",
                           final_category="feature-gap")
        row = store.all_findings(con)[0]
        self.assertEqual(row["product_judgment"], "必须补齐")
        self.assertEqual(row["final_category"], "feature-gap")

    def test_reclassify_preserves_pm_judgment(self):
        con = store.connect(_tmpdb())
        f = F.Finding(task_id="T1", rule="feature-gap",
                      suspected_category="feature-gap", subject="simular",
                      phenomenon="v1", evidence=[{"source": "log"}])
        fid = store.upsert_finding(con, f)
        store.set_judgment(con, fid, product_judgment="值得借鉴")
        # pipeline re-runs, machine re-classifies same finding with new phenomenon
        f2 = F.Finding(task_id="T1", rule="feature-gap",
                       suspected_category="feature-gap", subject="simular",
                       phenomenon="v2 updated", evidence=[{"source": "log"}])
        store.upsert_finding(con, f2)
        row = store.all_findings(con)[0]
        self.assertEqual(row["phenomenon"], "v2 updated")     # machine field updated
        self.assertEqual(row["product_judgment"], "值得借鉴")  # human field preserved


if __name__ == "__main__":
    unittest.main()
