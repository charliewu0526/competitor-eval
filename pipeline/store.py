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
import os
import pathlib
import sqlite3
import time

from pipeline import db as _db

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
    competitor_version   TEXT,               -- ADR-0017 数据新鲜度: 竞品版本/build 标识
    tested_at            REAL,               -- ADR-0017: 该次测试时间(epoch)
    stale                INTEGER DEFAULT 0,  -- ADR-0017: 超期标陈旧 0/1
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
    competitor_version   TEXT,               -- ADR-0017 数据新鲜度: 竞品版本/build 标识
    tested_at            REAL,               -- ADR-0017: 该次测试时间(epoch)
    stale                INTEGER DEFAULT 0,  -- ADR-0017: 超期标陈旧 0/1
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

-- === MR-1 (#37) 多人评测工场地基: 四实体 (PRD #36) =====================
-- 文件不进库(ADR-0019): 原始产物 + 日志包走服务端目录, 这里只存路径引用.

CREATE TABLE IF NOT EXISTS users (
    id                   TEXT PRIMARY KEY,   -- 自注册用户 id
    name                 TEXT,
    role                 TEXT NOT NULL DEFAULT 'intern',  -- intern | reviewer | owner (ADR-0014)
    created_ts           REAL
);

CREATE TABLE IF NOT EXISTS assignments (
    id                   TEXT PRIMARY KEY,   -- 领取任务单元 id
    task_id              TEXT NOT NULL,
    products_json        TEXT,               -- 参赛产品集合 [vio, rival...] (ADR-0015 整组对打)
    status               TEXT NOT NULL DEFAULT 'open',  -- open | claimed | submitted | abandoned
    claimed_by           TEXT,               -- users.id; open 时为 NULL
    claimed_ts           REAL,
    created_ts           REAL
);

CREATE TABLE IF NOT EXISTS submissions (
    id                   TEXT PRIMARY KEY,   -- 一个产品一次提交的一整包
    assignment_id        TEXT NOT NULL,
    product              TEXT NOT NULL,
    artifact_path        TEXT,               -- 原始产物目录路径引用(不入库)
    log_bundle_path      TEXT,               -- 执行日志包路径引用(必传, 不入库)
    manual_assertions_json TEXT,             -- 只能人看的客观断言人工勾选
    claimed_success      INTEGER,            -- 0/1/NULL: 该产品自称完成没(喂 H1)
    submitted_by         TEXT,               -- users.id
    submitted_ts         REAL,
    UNIQUE (assignment_id, product)          -- 一 Assignment 每产品一份 Submission
);

CREATE TABLE IF NOT EXISTS methods (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id              TEXT NOT NULL,
    product              TEXT NOT NULL,       -- 被提炼方法的竞品
    draft                TEXT NOT NULL,       -- 方法初稿(差距证据包上提炼)
    status               TEXT NOT NULL DEFAULT 'draft',  -- draft | approved | exported (方法复核闸)
    gated_by             TEXT,                -- 把关的 reviewer/PM users.id
    created_ts           REAL
);

-- === MR-3 (#39) 私发链接自注册登录 (ADR-0014 注册即 intern) ==============
-- invite: PM 私发的注册凭证. 无链接不能注册 (story 2 数据源可控, 不对公网开放).
--         一次性消费: used_by 落定后不能再注册. expires_ts NULL = 不过期.
CREATE TABLE IF NOT EXISTS invites (
    token                TEXT PRIMARY KEY,   -- 注册链接里的凭证 (随机不可猜)
    note                 TEXT,               -- 给谁的备注 (PM 记忆用)
    created_by           TEXT,               -- 签发者 users.id (owner)
    created_ts           REAL,
    expires_ts           REAL,               -- NULL = 不过期
    used_by              TEXT,               -- 注册成功后消费者 users.id; NULL = 未用
    used_ts              REAL
);

-- session: 登录后颁发的会话令牌. 会话可识别当前用户与角色 (story 1).
CREATE TABLE IF NOT EXISTS sessions (
    token                TEXT PRIMARY KEY,   -- 会话令牌 (bearer)
    user_id              TEXT NOT NULL,      -- users.id
    created_ts           REAL,
    expires_ts           REAL                -- NULL = 不过期
);
"""


def _parse_schema_columns(schema: str) -> dict[str, list[tuple[str, str]]]:
    """Derive {table: [(col_name, full_col_definition), ...]} from the SCHEMA DDL.

    Used to migrate pre-existing DBs: CREATE TABLE IF NOT EXISTS is a no-op on an
    existing table, so columns added to SCHEMA after a DB was first created never
    appear. We diff and ALTER them in (see _migrate). Lines that are table-level
    constraints (PRIMARY KEY (...), UNIQUE (...), FOREIGN KEY ...) are skipped —
    they aren't columns and can't be added via ALTER anyway.
    """
    import re
    tables: dict[str, list[tuple[str, str]]] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\);",
                          schema, re.DOTALL | re.IGNORECASE):
        name, body = m.group(1), m.group(2)
        cols: list[tuple[str, str]] = []
        for raw in body.split("\n"):
            line = raw.split("--", 1)[0].strip().rstrip(",").strip()
            if not line:
                continue
            if re.match(r"(?i)(PRIMARY KEY|UNIQUE|FOREIGN KEY|CHECK|CONSTRAINT)\b", line):
                continue
            col = line.split()[0]
            cols.append((col, line))
        tables[name] = cols
    return tables


def _migrate(con: sqlite3.Connection) -> list[str]:
    """Add any SCHEMA columns missing from an existing DB. Returns added "table.col".

    Idempotent + additive only — never drops/retypes. New columns carry their
    SCHEMA default (or NULL), so back-compat reads keep working. This is what
    rescues a DB built before A3's cost_* columns were introduced.
    """
    added: list[str] = []
    for table, cols in _parse_schema_columns(SCHEMA).items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue  # table doesn't exist yet -> executescript(SCHEMA) created it
        for col, ddl in cols:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
                added.append(f"{table}.{col}")
    if added:
        con.commit()
    return added


def connect(db_path: str | pathlib.Path | None = None,
            url: str | None = None):
    """Open the single-source store.

    Backend selection (PM 拍板: SQLite 默认、Postgres 就绪):
      * url 或环境变量 DATABASE_URL 指向 Postgres -> pg8000 连接, SCHEMA 按方言翻译。
      * 否则 -> stdlib sqlite3, 与迁移前完全一致(db_path 路径、_migrate PRAGMA 兜底
        全部原样), 现有测试作回归护栏。
    db_path 仅对 SQLite 后端有意义; PG 后端由 url 决定库。
    """
    resolved_url = url or os.environ.get("DATABASE_URL")
    if _db.dialect_for(resolved_url) == "postgres":
        con = _db.connect_url(resolved_url)
        con.executescript(_db.translate_ddl(SCHEMA, "postgres"))
        # PG 建表即完整, 无需 SQLite 的 ALTER 回填(_migrate 走 PRAGMA, SQLite-only)。
        return con
    p = pathlib.Path(db_path) if db_path else DEFAULT_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)   # creates missing tables
    _migrate(con)               # back-fills missing columns on pre-existing tables
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
            cost_model_calls, cost_usd, cost_source, transcript_excerpt, ts,
            competitor_version, tested_at, stale)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            transcript_excerpt=excluded.transcript_excerpt, ts=excluded.ts,
            competitor_version=excluded.competitor_version,
            tested_at=excluded.tested_at, stale=excluded.stale
    """, (rr.task_id, rr.product, rr.run_idx, rr.gate, rr.objective_passed,
          rr.objective_total, _b(rr.objective_failed_primary), rr.evidence_source,
          _b(rr.claimed_success), rr.cost_input_tokens, rr.cost_output_tokens,
          rr.cost_model_calls, rr.cost_usd, rr.cost_source,
          rr.transcript_excerpt, rr.ts,
          getattr(rr, "competitor_version", None), getattr(rr, "tested_at", None),
          _b(getattr(rr, "stale", False))))
    con.commit()


def upsert_score(con: sqlite3.Connection, sc: dict) -> None:
    """Persist a score_run() output dict (the seam OUTPUT)."""
    con.execute("""
        INSERT INTO scores (task_id, product, run_idx, gate, scored, reason,
            cross_layer, objective_ratio, sample_score, h1_honesty,
            subjective_json, disagreement_json, defects_json,
            competitor_version, tested_at, stale)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(task_id, product, run_idx) DO UPDATE SET
            gate=excluded.gate, scored=excluded.scored, reason=excluded.reason,
            cross_layer=excluded.cross_layer,
            objective_ratio=excluded.objective_ratio,
            sample_score=excluded.sample_score, h1_honesty=excluded.h1_honesty,
            subjective_json=excluded.subjective_json,
            disagreement_json=excluded.disagreement_json,
            defects_json=excluded.defects_json,
            competitor_version=excluded.competitor_version,
            tested_at=excluded.tested_at, stale=excluded.stale
    """, (sc["task_id"], sc["product"], sc["run_idx"], sc["gate"],
          _b(sc.get("scored", True)), sc.get("reason"),
          _b(sc.get("cross_layer")), sc.get("objective_ratio", 0.0),
          sc.get("sample_score"), sc.get("h1_honesty"),
          json.dumps(sc.get("subjective"), ensure_ascii=False),
          json.dumps(sc.get("disagreement_flagged"), ensure_ascii=False),
          json.dumps(sc.get("defects"), ensure_ascii=False),
          sc.get("competitor_version"), sc.get("tested_at"),
          _b(sc.get("stale", False))))
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


# === MR-1 (#37) 多人评测: 四实体 CRUD + 并发领取锁 ======================
def upsert_user(con, u: dict) -> None:
    """Persist a self-registered user. Idempotent on id. role defaults intern."""
    con.execute("""
        INSERT INTO users (id, name, role, created_ts)
        VALUES (?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, role=excluded.role
    """, (u["id"], u.get("name"), u.get("role", "intern"),
          u.get("created_ts", time.time())))
    con.commit()


def get_user(con, user_id: str) -> dict | None:
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def set_user_role(con, user_id: str, role: str) -> None:
    """PM promotes intern -> reviewer, etc. (ADR-0014)."""
    con.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    con.commit()


def all_users(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM users ORDER BY created_ts, id")]


def upsert_assignment(con, a: dict) -> None:
    """Persist an Assignment (一道对比任务的全部, ADR-0015). Idempotent on id.
    products_json holds the参赛产品集合 (Violoop + 同域竞品)."""
    con.execute("""
        INSERT INTO assignments (id, task_id, products_json, status,
            claimed_by, claimed_ts, created_ts)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            task_id=excluded.task_id, products_json=excluded.products_json,
            status=excluded.status, claimed_by=excluded.claimed_by,
            claimed_ts=excluded.claimed_ts
    """, (a["id"], a["task_id"],
          json.dumps(a.get("products"), ensure_ascii=False),
          a.get("status", "open"), a.get("claimed_by"),
          a.get("claimed_ts"), a.get("created_ts", time.time())))
    con.commit()


def get_assignment(con, assignment_id: str) -> dict | None:
    row = con.execute("SELECT * FROM assignments WHERE id=?",
                      (assignment_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["products"] = json.loads(d.get("products_json") or "null")
    except Exception:
        d["products"] = None
    return d


def open_assignments(con) -> list[dict]:
    """List assignments still up for grabs (未被领取)."""
    return [dict(r) for r in con.execute(
        "SELECT * FROM assignments WHERE status='open' ORDER BY created_ts, id")]


def claim_assignment(con, assignment_id: str, user_id: str) -> bool:
    """并发领取控制 (story 10): atomically claim an OPEN assignment for user_id.

    Returns True iff THIS caller won the claim; False if it was already claimed
    (another runner got there first, or it isn't open). The guard is the
    `status='open'` predicate in the UPDATE: SQLite serializes writers so exactly
    one concurrent UPDATE flips open->claimed and reports rowcount==1; the loser's
    UPDATE matches zero rows. On Postgres the same statement is used, backed by
    row locking (see pipeline.db.claim_assignment_sql for the SELECT FOR UPDATE
    variant) — same contract,教科书 UNIQUE/行锁解法 (#37 AC).
    """
    if _db.is_postgres(con):
        # 教科书行锁: 先 SELECT ... FOR UPDATE 锁住该行, 再判 open 再翻转.
        # 并发的第二请求在此 SELECT 处阻塞, 拿到锁时已见 status='claimed' -> 落败.
        row = con.execute(
            "SELECT status FROM assignments WHERE id=? FOR UPDATE",
            (assignment_id,)).fetchone()
        if not row or row["status"] != "open":
            con.commit()
            return False
        con.execute(
            "UPDATE assignments SET status='claimed', claimed_by=?, claimed_ts=? "
            "WHERE id=?", (user_id, time.time(), assignment_id))
        con.commit()
        return True
    cur = con.execute(
        "UPDATE assignments SET status='claimed', claimed_by=?, claimed_ts=? "
        "WHERE id=? AND status='open'",
        (user_id, time.time(), assignment_id))
    con.commit()
    return cur.rowcount == 1


def set_assignment_status(con, assignment_id: str, status: str) -> None:
    """submitted / abandoned (放弃或超时回到清单, story 12). Abandon reopens it."""
    if status == "abandoned":
        con.execute("UPDATE assignments SET status='open', claimed_by=NULL, "
                    "claimed_ts=NULL WHERE id=?", (assignment_id,))
    else:
        con.execute("UPDATE assignments SET status=? WHERE id=?",
                    (status, assignment_id))
    con.commit()


def upsert_submission(con, s: dict) -> int | str:
    """Persist a Submission (交付物: 原始产物 + 日志包 + 人工勾选断言).
    Files stay on disk — only path refs stored (ADR-0019). Idempotent on
    (assignment_id, product): 一 Assignment 每产品一份."""
    con.execute("""
        INSERT INTO submissions (id, assignment_id, product, artifact_path,
            log_bundle_path, manual_assertions_json, claimed_success,
            submitted_by, submitted_ts)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(assignment_id, product) DO UPDATE SET
            artifact_path=excluded.artifact_path,
            log_bundle_path=excluded.log_bundle_path,
            manual_assertions_json=excluded.manual_assertions_json,
            claimed_success=excluded.claimed_success,
            submitted_by=excluded.submitted_by, submitted_ts=excluded.submitted_ts
    """, (s["id"], s["assignment_id"], s["product"], s.get("artifact_path"),
          s.get("log_bundle_path"),
          json.dumps(s.get("manual_assertions"), ensure_ascii=False),
          _b(s.get("claimed_success")), s.get("submitted_by"),
          s.get("submitted_ts", time.time())))
    con.commit()
    row = con.execute("SELECT id FROM submissions WHERE assignment_id=? AND product=?",
                      (s["assignment_id"], s["product"])).fetchone()
    return row["id"]


def submissions_for(con, assignment_id: str) -> list[dict]:
    rows = con.execute("SELECT * FROM submissions WHERE assignment_id=? "
                       "ORDER BY product", (assignment_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["manual_assertions"] = json.loads(d.get("manual_assertions_json") or "null")
        except Exception:
            d["manual_assertions"] = None
        out.append(d)
    return out


def upsert_method(con, m: dict) -> int:
    """Persist a Method draft (差距证据包上提炼的方法初稿, 方法复核闸).
    status draft -> approved -> exported; only reviewer/PM can gate (enforced by
    the web layer in a later slice, not here)."""
    if m.get("id"):
        con.execute("""UPDATE methods SET task_id=?, product=?, draft=?,
                       status=?, gated_by=? WHERE id=?""",
                    (m["task_id"], m["product"], m["draft"],
                     m.get("status", "draft"), m.get("gated_by"), m["id"]))
        con.commit()
        return m["id"]
    cur = con.execute("""INSERT INTO methods (task_id, product, draft, status,
                         gated_by, created_ts) VALUES (?,?,?,?,?,?)""",
                      (m["task_id"], m["product"], m["draft"],
                       m.get("status", "draft"), m.get("gated_by"),
                       m.get("created_ts", time.time())))
    con.commit()
    row = con.execute("SELECT id FROM methods WHERE rowid=?",
                      (cur.lastrowid,)).fetchone()
    return row["id"]


def set_method_status(con, method_id: int, status: str,
                      gated_by: str | None = None) -> None:
    """方法复核闸: reviewer/PM 把关 draft->approved, 再 approved->exported."""
    con.execute("UPDATE methods SET status=?, gated_by=COALESCE(?, gated_by) "
                "WHERE id=?", (status, gated_by, method_id))
    con.commit()


def all_methods(con, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM methods"
    args: tuple = ()
    if status is not None:
        sql += " WHERE status=?"
        args = (status,)
    sql += " ORDER BY id"
    return [dict(r) for r in con.execute(sql, args)]


# === MR-3 (#39) 私发链接自注册登录: invites + sessions ===================
def create_invite(con, inv: dict) -> str:
    """PM 签发一张私发注册链接凭证 (无链接不能注册, story 2)."""
    con.execute("""
        INSERT INTO invites (token, note, created_by, created_ts, expires_ts)
        VALUES (?,?,?,?,?)
    """, (inv["token"], inv.get("note"), inv.get("created_by"),
          inv.get("created_ts", time.time()), inv.get("expires_ts")))
    con.commit()
    return inv["token"]


def get_invite(con, token: str) -> dict | None:
    row = con.execute("SELECT * FROM invites WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def invite_is_valid(con, token: str, now: float | None = None) -> bool:
    """有效 = 存在 + 未被消费 + 未过期. 决定「持链接能不能注册」."""
    inv = get_invite(con, token)
    if not inv:
        return False
    if inv.get("used_by"):
        return False
    exp = inv.get("expires_ts")
    if exp is not None and (now or time.time()) > exp:
        return False
    return True


def consume_invite(con, token: str, user_id: str, now: float | None = None) -> bool:
    """一次性消费: 原子把 invite 绑定到注册者. 并发下仅一人赢 (used_by IS NULL 守卫)."""
    ts = now or time.time()
    if _db.is_postgres(con):
        row = con.execute("SELECT used_by, expires_ts FROM invites WHERE token=? FOR UPDATE",
                          (token,)).fetchone()
        if not row or row["used_by"] is not None or \
           (row["expires_ts"] is not None and ts > row["expires_ts"]):
            con.commit()
            return False
        con.execute("UPDATE invites SET used_by=?, used_ts=? WHERE token=?",
                    (user_id, ts, token))
        con.commit()
        return True
    cur = con.execute(
        "UPDATE invites SET used_by=?, used_ts=? WHERE token=? AND used_by IS NULL "
        "AND (expires_ts IS NULL OR expires_ts>=?)",
        (user_id, ts, token, ts))
    con.commit()
    return cur.rowcount == 1


def all_invites(con) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM invites ORDER BY created_ts, token")]


def create_session(con, sess: dict) -> str:
    """登录成功颁发会话令牌 (bearer). 会话可识别当前用户与角色 (story 1)."""
    con.execute("""
        INSERT INTO sessions (token, user_id, created_ts, expires_ts)
        VALUES (?,?,?,?)
    """, (sess["token"], sess["user_id"],
          sess.get("created_ts", time.time()), sess.get("expires_ts")))
    con.commit()
    return sess["token"]


def get_session(con, token: str) -> dict | None:
    row = con.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def session_user(con, token: str, now: float | None = None) -> dict | None:
    """解析会话令牌 -> 当前用户 (含 role). 过期/无效 -> None."""
    sess = get_session(con, token)
    if not sess:
        return None
    exp = sess.get("expires_ts")
    if exp is not None and (now or time.time()) > exp:
        return None
    return get_user(con, sess["user_id"])


def delete_session(con, token: str) -> None:
    """登出: 撤销会话令牌."""
    con.execute("DELETE FROM sessions WHERE token=?", (token,))
    con.commit()


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
