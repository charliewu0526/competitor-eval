"""MR-1 (#37): SQLite / Postgres 方言抽象层.

设计立场(PM 已拍板 2026-07-27):**SQLite 默认、Postgres 就绪**。
- 无 DATABASE_URL(默认/测试/本机无 PG)-> 走 stdlib sqlite3, 行为与迁移前一字不差,
  现有 310 测试全绿作回归护栏。
- 有 DATABASE_URL(自托管 Postgres)-> 走纯 Python 驱动 pg8000, store 层同一套 API,
  DDL / 占位符 / 自增主键在此模块按方言翻译。并发领取的 SELECT FOR UPDATE 在
  Postgres 上由此层提供(SQLite 靠串行化写者达到同一契约, 见 store.claim_assignment)。

真正的 Postgres server 尚未部署(本机无 postgres/brew/docker), 故 PG 路径以
「翻译函数纯单测 + 驱动可选导入」形态就绪, 配 DATABASE_URL 即可穿通 —— 显式登记
为技术债(ADR-0019 精神: 占位先就绪, 环境到位再拉通)。

本模块的翻译函数**不碰数据库**, 纯字符串 in/out, 可独立单测。
"""
from __future__ import annotations
import re


def dialect_for(url: str | None) -> str:
    """URL -> 'postgres' | 'sqlite'. None/空 => sqlite(默认)."""
    if not url:
        return "sqlite"
    u = url.strip().lower()
    if u.startswith(("postgres://", "postgresql://", "pg8000://")):
        return "postgres"
    return "sqlite"


def translate_ddl(sqlite_ddl: str, dialect: str) -> str:
    """把仓库里手写的 SQLite DDL 翻成目标方言。sqlite 时原样返回。

    Postgres 差异(覆盖本仓库 SCHEMA 实际用到的构造):
      * INTEGER PRIMARY KEY AUTOINCREMENT -> BIGSERIAL PRIMARY KEY (自增主键)
      * REAL   -> DOUBLE PRECISION
      * `stale INTEGER DEFAULT 0` 等布尔位仍用 INTEGER(0/1)——store._b() 已统一
        产出 0/1/None, 两库都吃 INTEGER, 不引入 BOOLEAN 方言分叉。
      * `CREATE TABLE IF NOT EXISTS` / `ON CONFLICT(...) DO UPDATE` 两库同语法, 不动。
    """
    if dialect == "sqlite":
        return sqlite_ddl
    if dialect != "postgres":
        raise ValueError(f"unknown dialect: {dialect!r}")
    out = sqlite_ddl
    # 自增主键: SQLite 的 INTEGER PRIMARY KEY AUTOINCREMENT -> PG 的 BIGSERIAL
    out = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
                 "BIGSERIAL PRIMARY KEY", out, flags=re.IGNORECASE)
    # 浮点: SQLite REAL -> PG DOUBLE PRECISION (词边界, 不误伤列名)
    out = re.sub(r"\bREAL\b", "DOUBLE PRECISION", out)
    return out


def _strip_line_comments(ddl: str) -> str:
    """去掉每行的 `-- ...` 尾注释(整行或行内)。必须在按 `;` 拆分前做 ——
    否则注释里的分号(如 `-- users.id; open 时为 NULL`)会把 CREATE TABLE 切断。"""
    return "\n".join(ln.split("--", 1)[0].rstrip() for ln in ddl.splitlines())


def split_statements(ddl: str) -> list[str]:
    """把多语句 DDL 脚本拆成单条 —— pg8000 的 execute 一次只吃一条,
    不像 sqlite3 有 executescript。先剥注释(避免注释内分号误切), 再按分号拆,
    丢弃空片。"""
    clean = _strip_line_comments(ddl)
    return [s.strip() for s in clean.split(";") if s.strip()]


def qmark_to_format(sql: str) -> str:
    """占位符方言: SQLite 的 ? -> Postgres(pg8000 paramstyle=format)的 %s。

    只替换 SQL 语法位置的 '?'——本仓库 SQL 不含字符串字面量里的问号, 故直接替换安全;
    同时把已有的裸 '%' 转义为 '%%' 以免与 format 冲突(本仓库 SQL 目前无 %, 防御性)。
    """
    return sql.replace("%", "%%").replace("?", "%s")


def is_postgres(con) -> bool:
    """运行时判断一个连接是否是 Postgres 包装(store 里据此选并发锁语句)。"""
    return getattr(con, "_ce_dialect", "sqlite") == "postgres"


# --- Postgres 连接(可选依赖 pg8000, 未装/未配 URL 时不导入)---------------
def connect_url(url: str):
    """用 pg8000 连 Postgres, 返回一个 sqlite3-like 包装。

    包装目标: store.py 里对 con 的用法(con.execute(sql, params) -> cursor,
    cursor.fetchone()/fetchall() -> Row-like 支持 row['col'] 与 dict(row),
    cursor.rowcount, con.commit())在 PG 上等价可用, 免得 store 到处写方言分支。

    仅当真的要连 PG 时才被调用, 因此 import pg8000 延迟到这里。
    """
    try:
        import pg8000.dbapi as pg  # 纯 Python 驱动, pip install pg8000
    except ImportError as e:  # pragma: no cover - 环境未装驱动时的清晰报错
        raise RuntimeError(
            "DATABASE_URL 指向 Postgres 但未安装驱动。请 `pip install pg8000` "
            "(纯 Python, 无需编译)。") from e
    from urllib.parse import urlparse, unquote
    p = urlparse(url)
    raw = pg.connect(
        user=unquote(p.username) if p.username else None,
        password=unquote(p.password) if p.password else None,
        host=p.hostname or "127.0.0.1",
        port=p.port or 5432,
        database=(p.path or "/").lstrip("/") or None,
    )
    return _PGConn(raw)


class _PGRow(dict):
    """dict 子类: 同时支持 row['col'](dict)与 row[0](位置), 贴近 sqlite3.Row。"""

    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._values = list(values)

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._values[k]
        return super().__getitem__(k)


class _PGCursor:
    def __init__(self, cur):
        self._cur = cur

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):  # pragma: no cover - PG 用 RETURNING/序列, 本仓库不依赖
        return None

    def _cols(self):
        desc = self._cur.description
        return [c[0] for c in desc] if desc else []

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return _PGRow(self._cols(), row)

    def fetchall(self):
        cols = self._cols()
        return [_PGRow(cols, r) for r in self._cur.fetchall()]

    def __iter__(self):
        cols = self._cols()
        for r in self._cur.fetchall():
            yield _PGRow(cols, r)


class _PGConn:
    """sqlite3.Connection-like 包装 over pg8000, 只覆盖 store.py 用到的表面。"""
    _ce_dialect = "postgres"

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):  # 翻占位符 ?->%s
        cur = self._raw.cursor()
        cur.execute(qmark_to_format(sql), tuple(params))
        return _PGCursor(cur)

    def executescript(self, script):  # 拆多语句逐条执行
        cur = self._raw.cursor()
        for stmt in split_statements(script):
            cur.execute(stmt)
        return _PGCursor(cur)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()
