"""S1: SQLite single source of truth for runs / scores / findings.

Replaces the hand-maintained Markdown board as the authoritative store. The
board renders FROM this DB (Streamlit live, or md/html export). PM edits a
finding's 产品判断 / 最终分类 in the board and it writes back HERE.

Design notes:
  * Pure stdlib sqlite3, single file, no ORM, no server. (PRD: SQLite 单一数据源)
  * Idempotent upserts keyed by natural keys so re-running the pipeline updates
    rows instead of duplicating them.
  * JSON blobs for nested structures (subjective medians, evidence, repro) —
    we query/rank on scalar columns, keep detail in JSON.
  * honesty (h1_honesty) is its OWN column, never folded into capability score.
"""
from __future__ import annotations
import json
import pathlib
import sqlite3
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "board" / "competitor_eval.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    task_id              TEXT NOT NULL,
    product              TEXT NOT NULL,
    run_idx              INTEGER NOT NULL,
    gate                 TEXT NOT NULL,
    objective_passed     INTEGER DEFAULT 0,
    objective_total      INTEGER DEFAULT 0,
    objective_failed_primary INTEGER DEFAULT 0,
    evidence_source      TEXT DEFAULT 'unavailable',
    claimed_success      INTEGER,            -- 0/1/NULL
    cost_input_tokens    INTEGER DEFAULT 0,  -- A3: 技术效率 (token 用量)
    cost_output_tokens   INTEGER DEFAULT 0,
    cost_model_calls     INTEGER DEFAULT 0,  -- A3: 架构效率 (来回轮数)
    cost_usd             REAL,               -- A3: 商业效率, NULL=unavailable/缺价
    cost_source          TEXT DEFAULT 'unavailable',
    transcript_excerpt   TEXT DEFAULT '',
    ts                   REAL,
    PRIMARY KEY (task_id, product, run_idx)
);

CREATE TABLE IF NOT EXISTS scores (
    task_id              TEXT NOT NULL,
    product              TEXT NOT NULL,
    run_idx              INTEGER NOT NULL,
    gate                 TEXT NOT NULL,
    scored               INTEGER DEFAULT 1,  -- 0 => not a fair head-to-head
    reason               TEXT,
    cross_layer          INTEGER DEFAULT 0,
    objective_ratio      REAL DEFAULT 0,
    sample_score         REAL,               -- capability 0..1, NULL when unscored
    h1_honesty           INTEGER,            -- INDEPENDENT axis 1-5, NULL if no claim
    subjective_json      TEXT,               -- {dim: median}
    disagreement_json    TEXT,               -- [dims flagged]
    defects_json         TEXT,               -- [defect dicts]
    PRIMARY KEY (task_id, product, run_idx)
);

CREATE TABLE IF NOT EXISTS findings (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id              TEXT NOT NULL,
    rule                 TEXT NOT NULL,
    suspected_category   TEXT NOT NULL,
    subject              TEXT NOT NULL,
    phenomenon           TEXT NOT NULL,
    evidence_json        TEXT,
    -- PM-fillable (machine leaves NULL):
    product_judgment     TEXT,
    final_category       TEXT,
    -- bug routing:
    routed_to            TEXT,
    bug_repro_json       TEXT,
    created_ts           REAL,
    UNIQUE (task_id, rule, subject)          -- re-classify updates, not dupes
);

CREATE TABLE IF NOT EXISTS authorizations (
    subject              TEXT PRIMARY KEY,   -- "reviewer:panel" | "verifier:claude"
    role                 TEXT NOT NULL,      -- "reviewer" | "verifier"
    status               TEXT NOT NULL,      -- authorized | revoked | uncalibrated
    kappa                REAL,               -- Cohen's kappa vs human gold (recorded)
    agreement            REAL,               -- raw observed agreement (recorded)
    n_samples            INTEGER DEFAULT 0,
    model_fingerprint    TEXT,               -- panel members + model versions
    rubric_fingerprint   TEXT,               -- hash of dims + anchors
    bias_profile_json    TEXT,               -- per-model 宽严 offset, RECORD-ONLY
    confusion_json       TEXT,               -- kappa confusion matrix (audit)
    calibrated_ts        REAL,
    revoked_reason       TEXT
);

CREATE TABLE IF NOT EXISTS spot_check_queue (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id              TEXT NOT NULL,
    product              TEXT NOT NULL,
    run_idx              INTEGER NOT NULL,
    stratum              TEXT NOT NULL,      -- contradiction | high-risk | normal
    reason               TEXT NOT NULL,      -- 为什么进队列（分层原因，给人看）
    status               TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | anomaly
    checked_by           TEXT,
    verdict_note         TEXT,
    enqueued_ts          REAL,
    checked_ts           REAL,
    UNIQUE (task_id, product, run_idx)       -- 重建队列更新分层，不覆盖人工结论
);
"""


def connect(db_path: str | pathlib.Path | None = None) -> sqlite3.Connection:
    p = pathlib.Path(db_path) if db_path else DEFAULT_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _b(v):
    """bool|None -> 0/1/None for SQLite."""
    return None if v is None else int(bool(v))


# --- writes ---------------------------------------------------------------
def upsert_run(con: sqlite3.Connection, rr) -> None:
    """Persist a RunRecord (the seam INPUT). Idempotent on (task,product,run)."""
    con.execute("""
        INSERT INTO runs (task_id, product, run_idx, gate, objective_passed,
            objective_total, objective_failed_primary, evidence_source,
            claimed_success, cost_input_tokens, cost_output_tokens,
            cost_model_calls, cost_usd, cost_source, transcript_excerpt, ts)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(task_id, product, run_idx) DO UPDATE SET
            gate=excluded.gate, objective_passed=excluded.objective_passed,
            objective_total=excluded.objective_total,
            objective_failed_primary=excluded.objective_failed_primary,
            evidence_source=excluded.evidence_source,
            claimed_success=excluded.claimed_success,
            cost_input_tokens=excluded.cost_input_tokens,
            cost_output_tokens=excluded.cost_output_tokens,
            cost_model_calls=excluded.cost_model_calls,
            cost_usd=excluded.cost_usd, cost_source=excluded.cost_source,
            transcript_excerpt=excluded.transcript_excerpt, ts=excluded.ts
    """, (rr.task_id, rr.product, rr.run_idx, rr.gate, rr.objective_passed,
          rr.objective_total, _b(rr.objective_failed_primary), rr.evidence_source,
          _b(rr.claimed_success), rr.cost_input_tokens, rr.cost_output_tokens,
          rr.cost_model_calls, rr.cost_usd, rr.cost_source,
          rr.transcript_excerpt, rr.ts))
    con.commit()


def upsert_score(con: sqlite3.Connection, sc: dict) -> None:
    """Persist a score_run() output dict (the seam OUTPUT)."""
    con.execute("""
        INSERT INTO scores (task_id, product, run_idx, gate, scored, reason,
            cross_layer, objective_ratio, sample_score, h1_honesty,
            subjective_json, disagreement_json, defects_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(task_id, product, run_idx) DO UPDATE SET
            gate=excluded.gate, scored=excluded.scored, reason=excluded.reason,
            cross_layer=excluded.cross_layer,
            objective_ratio=excluded.objective_ratio,
            sample_score=excluded.sample_score, h1_honesty=excluded.h1_honesty,
            subjective_json=excluded.subjective_json,
            disagreement_json=excluded.disagreement_json,
            defects_json=excluded.defects_json
    """, (sc["task_id"], sc["product"], sc["run_idx"], sc["gate"],
          _b(sc.get("scored", True)), sc.get("reason"),
          _b(sc.get("cross_layer")), sc.get("objective_ratio", 0.0),
          sc.get("sample_score"), sc.get("h1_honesty"),
          json.dumps(sc.get("subjective"), ensure_ascii=False),
          json.dumps(sc.get("disagreement_flagged"), ensure_ascii=False),
          json.dumps(sc.get("defects"), ensure_ascii=False)))
    con.commit()


def upsert_finding(con: sqlite3.Connection, f) -> int:
    """Persist a Finding. Re-classify UPDATES machine fields but PRESERVES the
    PM-filled product_judgment/final_category (machine never overwrites human)."""
    d = f.as_dict() if hasattr(f, "as_dict") else dict(f)
    con.execute("""
        INSERT INTO findings (task_id, rule, suspected_category, subject,
            phenomenon, evidence_json, product_judgment, final_category,
            routed_to, bug_repro_json, created_ts)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(task_id, rule, subject) DO UPDATE SET
            suspected_category=excluded.suspected_category,
            phenomenon=excluded.phenomenon, evidence_json=excluded.evidence_json,
            routed_to=excluded.routed_to, bug_repro_json=excluded.bug_repro_json
    """, (d["task_id"], d["rule"], d["suspected_category"], d["subject"],
          d["phenomenon"], json.dumps(d.get("evidence"), ensure_ascii=False),
          d.get("product_judgment"), d.get("final_category"),
          d.get("routed_to"), json.dumps(d.get("bug_repro"), ensure_ascii=False),
          time.time()))
    con.commit()
    row = con.execute("SELECT id FROM findings WHERE task_id=? AND rule=? AND subject=?",
                      (d["task_id"], d["rule"], d["subject"])).fetchone()
    return row["id"]


def set_judgment(con: sqlite3.Connection, finding_id: int,
                 product_judgment: str | None = None,
                 final_category: str | None = None) -> None:
    """PM writes back 产品判断 / 最终分类 from the board. This is the ONE place
    human judgment enters the DB — machine classify() never touches these."""
    con.execute("""UPDATE findings SET product_judgment=COALESCE(?, product_judgment),
                   final_category=COALESCE(?, final_category) WHERE id=?""",
                (product_judgment, final_category, finding_id))
    con.commit()


# --- G2: authorization records -------------------------------------------
def upsert_authorization(con: sqlite3.Connection, a: dict) -> None:
    """Persist an authorization record (the G2 calibrate/check output).

    Idempotent on `subject`. Stores kappa/agreement/bias as RECORD-ONLY data —
    nothing here ever feeds back into a run's sample_score (ADR-0005/0011).
    """
    con.execute("""
        INSERT INTO authorizations (subject, role, status, kappa, agreement,
            n_samples, model_fingerprint, rubric_fingerprint, bias_profile_json,
            confusion_json, calibrated_ts, revoked_reason)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(subject) DO UPDATE SET
            role=excluded.role, status=excluded.status, kappa=excluded.kappa,
            agreement=excluded.agreement, n_samples=excluded.n_samples,
            model_fingerprint=excluded.model_fingerprint,
            rubric_fingerprint=excluded.rubric_fingerprint,
            bias_profile_json=excluded.bias_profile_json,
            confusion_json=excluded.confusion_json,
            calibrated_ts=excluded.calibrated_ts,
            revoked_reason=excluded.revoked_reason
    """, (a["subject"], a["role"], a["status"], a.get("kappa"),
          a.get("agreement"), a.get("n_samples", 0), a.get("model_fingerprint"),
          a.get("rubric_fingerprint"),
          json.dumps(a.get("bias_profile"), ensure_ascii=False),
          json.dumps(a.get("confusion"), ensure_ascii=False),
          a.get("calibrated_ts"), a.get("revoked_reason")))
    con.commit()


def get_authorization(con: sqlite3.Connection, subject: str) -> dict | None:
    row = con.execute("SELECT * FROM authorizations WHERE subject=?",
                      (subject,)).fetchone()
    return dict(row) if row else None


def set_authorization_status(con: sqlite3.Connection, subject: str, status: str,
                             revoked_reason: str | None = None) -> None:
    """Revoke / restore. Revoking does NOT erase the recorded kappa/bias —
    those stay for audit; only status + reason change."""
    con.execute("""UPDATE authorizations SET status=?,
                   revoked_reason=COALESCE(?, revoked_reason) WHERE subject=?""",
                (status, revoked_reason, subject))
    con.commit()


def all_authorizations(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM authorizations ORDER BY subject")]


# --- G3: spot-check queue -------------------------------------------------
def enqueue_spot_check(con: sqlite3.Connection, *, task_id: str, product: str,
                       run_idx: int, stratum: str, reason: str) -> int:
    """Add a run to the spot-check queue. Idempotent on (task,product,run):
    re-enqueue REFRESHES stratum/reason but NEVER clobbers a human verdict
    (status/checked_* are left untouched on conflict)."""
    con.execute("""
        INSERT INTO spot_check_queue (task_id, product, run_idx, stratum,
            reason, status, enqueued_ts)
        VALUES (?,?,?,?,?, 'pending', ?)
        ON CONFLICT(task_id, product, run_idx) DO UPDATE SET
            stratum=excluded.stratum, reason=excluded.reason
    """, (task_id, product, run_idx, stratum, reason, time.time()))
    con.commit()
    row = con.execute("""SELECT id FROM spot_check_queue
                         WHERE task_id=? AND product=? AND run_idx=?""",
                      (task_id, product, run_idx)).fetchone()
    return row["id"]


def record_spot_check(con: sqlite3.Connection, queue_id: int, *, status: str,
                      checked_by: str | None = None,
                      verdict_note: str | None = None) -> None:
    """Write back a human spot-check result. status: 'ok' | 'anomaly'."""
    con.execute("""UPDATE spot_check_queue SET status=?, checked_by=?,
                   verdict_note=?, checked_ts=? WHERE id=?""",
                (status, checked_by, verdict_note, time.time(), queue_id))
    con.commit()


def spot_check_queue(con: sqlite3.Connection,
                     status: str | None = None) -> list[dict]:
    """List queue items, optionally filtered by status. Ordered so 100%
    strata (contradiction/high-risk) surface above random-sampled normals."""
    sql = "SELECT * FROM spot_check_queue"
    args: tuple = ()
    if status is not None:
        sql += " WHERE status=?"
        args = (status,)
    sql += (" ORDER BY CASE stratum WHEN 'high-risk' THEN 0 "
            "WHEN 'contradiction' THEN 1 ELSE 2 END, id")
    return [dict(r) for r in con.execute(sql, args)]


# --- reads ----------------------------------------------------------------
def all_scores(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM scores ORDER BY task_id, product")]


def all_findings(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM findings ORDER BY id")]


def cost_with_completion(con: sqlite3.Connection) -> list[dict]:
    """A3: cost read SIDE BY SIDE with完成度 — never cost alone.

    ADR-0008 铁律: 成本必须和「是否真完成」一起看, 否则「摆烂没干完」会伪装成「省 token」.
    So this join glues each run's cost (tokens/calls/$/source from `runs`) to its
    completion signals (sample_score/objective_ratio/objective_failed_primary from
    `scores`). A row with cost_usd present but sample_score=0 is exactly the
    「省 token=没干活」trap this view makes visible.

    `cost_priced` is True iff cost_usd is a real number (not unavailable / 缺价).
    """
    rows = con.execute("""
        SELECT r.task_id, r.product, r.run_idx,
               r.cost_input_tokens, r.cost_output_tokens, r.cost_model_calls,
               r.cost_usd, r.cost_source,
               s.sample_score, s.objective_ratio, r.objective_failed_primary,
               s.scored, s.reason, r.gate
        FROM runs r
        LEFT JOIN scores s
          ON r.task_id=s.task_id AND r.product=s.product AND r.run_idx=s.run_idx
        ORDER BY r.task_id, r.product, r.run_idx
    """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["cost_priced"] = d["cost_usd"] is not None
        out.append(d)
    return out


def persist_eval(con: sqlite3.Connection, runs: list, scores: list[dict],
                 findings: list) -> None:
    """Bulk-persist one pipeline run's worth of records into all three tables."""
    for rr in runs:
        upsert_run(con, rr)
    for sc in scores:
        upsert_score(con, sc)
    for f in findings:
        upsert_finding(con, f)
