"""代码健康体检回归测试: Postgres 路径 P0/P1 修复 (F-1 / F-2 / F-3 / F-9).

Run: python -m unittest tests.test_health_pg_fixes_mr14 -v

这些是 improve-codebase-architecture 体检发现的真实隐患, 全都在 PG 路径且本机无
PG server, 故用**轻量 fake 连接**验证方言层的行为契约 (不需真 server):

  F-1: _PGConn 必须有 rollback() —— 否则并发领取/注册落败方崩 AttributeError。
  F-2: db.pg_migrate 必须把已存在表缺的列 ALTER 补齐 (用 information_schema)。
  F-3: store._migrate 用列名而非位置索引取 PRAGMA 列名 (SQLite 侧, 真库验证)。

真连 PG 的端到端契约仍由 test_postgres_passthrough_mr1b 覆盖 (需 DATABASE_URL)。
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import db, store


# --- F-1: _PGConn 有 rollback() ------------------------------------------
class PGConnRollback(unittest.TestCase):
    def test_pgconn_exposes_rollback(self):
        """_PGConn 必须暴露 rollback 且委托给底层 pg8000 连接 (F-1).

        store.claim_assignment / consume_invite 的 PG 失败路径调 con.rollback()
        释放 FOR UPDATE 行锁; 缺此方法则并发落败方崩 AttributeError。
        """
        calls = {"rollback": 0, "commit": 0}

        class _FakeRaw:
            def rollback(self):
                calls["rollback"] += 1

            def commit(self):
                calls["commit"] += 1

            def close(self):
                pass

        con = db._PGConn(_FakeRaw())
        self.assertTrue(hasattr(con, "rollback"), "_PGConn 缺 rollback (F-1 回归)")
        con.rollback()
        self.assertEqual(calls["rollback"], 1, "rollback 未委托底层连接")

    def test_pgconn_is_flagged_postgres(self):
        # is_postgres 靠 _ce_dialect 判定, 修复不能动这个契约。
        class _FakeRaw:
            pass
        self.assertTrue(db.is_postgres(db._PGConn(_FakeRaw())))


# --- F-2: pg_migrate 补齐已存在表的缺失列 --------------------------------
class PGMigrateBackfill(unittest.TestCase):
    """用 fake PG 连接验证 pg_migrate 的探查+ALTER 逻辑 (无需真 server)。"""

    def _fake_con(self, existing_cols: dict):
        """existing_cols: {table: set(col)}。模拟 information_schema 查询 + ALTER 记录。"""
        altered: list[str] = []

        class _FakeCursor:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        class _FakeCon:
            _ce_dialect = "postgres"

            def execute(self, sql, params=()):
                low = sql.lower()
                if "information_schema.columns" in low:
                    table = params[0]
                    cols = existing_cols.get(table, set())
                    # 返回 _PGRow-like: 支持 r["column_name"]
                    return _FakeCursor([{"column_name": c} for c in cols])
                if low.startswith("alter table"):
                    altered.append(sql)
                    return _FakeCursor([])
                return _FakeCursor([])

            def commit(self):
                pass

        return _FakeCon(), altered

    def test_missing_columns_are_altered_in(self):
        # runs 表只有旧列, 缺 SCHEMA 里新加的 stale/tested_at 等 -> 必须 ALTER 补。
        schema_cols = store._parse_schema_columns(store.SCHEMA)
        con, altered = self._fake_con({"runs": {"task_id", "product", "run_idx"}})
        added = db.pg_migrate(con, {"runs": schema_cols["runs"]})
        # 应补齐 runs 里除已有三列外的所有列
        self.assertTrue(added, "pg_migrate 未补任何列 (F-2 回归)")
        self.assertTrue(any("stale" in a for a in added),
                        f"未补 stale 列: {added}")
        self.assertEqual(len(added), len(altered), "added 记录数与 ALTER 次数不符")

    def test_absent_table_is_skipped(self):
        # 表还不存在 (information_schema 空) -> 不 ALTER (executescript 已建全)。
        schema_cols = store._parse_schema_columns(store.SCHEMA)
        con, altered = self._fake_con({})   # 无任何表
        added = db.pg_migrate(con, {"runs": schema_cols["runs"]})
        self.assertEqual(added, [], "空表不该被 ALTER")
        self.assertEqual(altered, [])

    def test_fully_migrated_table_is_noop(self):
        # 已有全部列 -> 无需 ALTER。
        schema_cols = store._parse_schema_columns(store.SCHEMA)
        have = {c for c, _ddl in schema_cols["users"]}
        con, altered = self._fake_con({"users": have})
        added = db.pg_migrate(con, {"users": schema_cols["users"]})
        self.assertEqual(added, [], f"列已齐却仍 ALTER: {added}")


# --- F-3: SQLite _migrate 用列名取 PRAGMA (真库验证) ----------------------
class SQLiteMigrateByName(unittest.TestCase):
    def test_migrate_backfills_missing_column_on_existing_db(self):
        """真 SQLite: 老库缺 SCHEMA 新列时 _migrate 用 r['name'] 探查并 ALTER 补齐。

        建一张只有部分列的老 runs 表, connect() 应把缺的列全补上 (F-3: 名称访问
        取代脆弱的位置索引 r[1])。
        """
        import sqlite3
        p = str(pathlib.Path(tempfile.mkdtemp()) / "old.db")
        raw = sqlite3.connect(p)
        raw.execute("CREATE TABLE runs (task_id TEXT, product TEXT, run_idx INTEGER)")
        raw.commit()
        raw.close()
        # connect() 内部会 executescript(SCHEMA) + _migrate 回填。
        con = store.connect(p)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(runs)")}
        for c in ("gate", "stale", "competitor_version", "tested_at", "cost_usd"):
            self.assertIn(c, cols, f"_migrate 未补 {c} (F-3 回归)")
        con.close()


if __name__ == "__main__":
    unittest.main()
