"""MR-1 (#37): 方言抽象层纯字符串翻译单测 (不碰数据库).

Run: python -m unittest tests.test_db_dialect_mr1 -v

覆盖 #37 AC「并发领取锁就位 / DATABASE_URL 切 Postgres」的地基:
  - dialect_for: URL -> sqlite | postgres, 默认 sqlite
  - translate_ddl: AUTOINCREMENT -> BIGSERIAL, REAL -> DOUBLE PRECISION, sqlite 原样
  - qmark_to_format: ? -> %s
  - split_statements: 多语句脚本拆条 (pg8000 一次一条)
真正连 PG 需 DATABASE_URL + pg8000 server, 属技术债(本机无 server, ADR-0019)。
"""
from __future__ import annotations
import unittest
from pipeline import db
from pipeline.store import SCHEMA


class DialectFor(unittest.TestCase):
    def test_none_is_sqlite(self):
        self.assertEqual(db.dialect_for(None), "sqlite")
        self.assertEqual(db.dialect_for(""), "sqlite")

    def test_postgres_urls(self):
        for u in ("postgres://u:p@h:5432/db", "postgresql://h/db",
                  "PG8000://h/db"):
            self.assertEqual(db.dialect_for(u), "postgres", u)

    def test_sqlite_path_is_sqlite(self):
        self.assertEqual(db.dialect_for("/tmp/board/x.db"), "sqlite")


class TranslateDDL(unittest.TestCase):
    def test_sqlite_passthrough_identical(self):
        self.assertEqual(db.translate_ddl(SCHEMA, "sqlite"), SCHEMA)

    def test_autoincrement_becomes_bigserial(self):
        pg = db.translate_ddl(SCHEMA, "postgres")
        self.assertNotIn("AUTOINCREMENT", pg.upper())
        self.assertIn("BIGSERIAL PRIMARY KEY", pg)

    def test_real_becomes_double_precision(self):
        pg = db.translate_ddl("CREATE TABLE t (ts REAL, k INTEGER);", "postgres")
        self.assertIn("DOUBLE PRECISION", pg)
        self.assertNotIn(" REAL", pg)

    def test_unknown_dialect_raises(self):
        with self.assertRaises(ValueError):
            db.translate_ddl(SCHEMA, "mysql")


class QmarkToFormat(unittest.TestCase):
    def test_qmark_replaced(self):
        self.assertEqual(db.qmark_to_format("INSERT INTO t VALUES (?,?,?)"),
                         "INSERT INTO t VALUES (%s,%s,%s)")

    def test_bare_percent_escaped(self):
        # 防御: 已有的裸 % 需转义, 免与 pg8000 format paramstyle 冲突.
        self.assertEqual(db.qmark_to_format("WHERE x LIKE '%a' AND y=?"),
                         "WHERE x LIKE '%%a' AND y=%s")


class SplitStatements(unittest.TestCase):
    def test_schema_splits_into_all_tables(self):
        stmts = db.split_statements(SCHEMA)
        blob = " ".join(stmts).lower()
        for t in ("runs", "scores", "findings", "authorizations",
                  "spot_check_queue", "users", "assignments",
                  "submissions", "methods"):
            self.assertIn(f"table if not exists {t}", blob, t)
        # 每条都应是有效 DDL (CREATE TABLE 或 CREATE INDEX), 无空片/纯注释残留
        for s in stmts:
            up = s.upper()
            self.assertTrue("CREATE TABLE" in up or "CREATE INDEX" in up
                            or "CREATE UNIQUE INDEX" in up, s)

    def test_comment_only_chunk_dropped(self):
        self.assertEqual(db.split_statements("-- just a comment\n"), [])


class IsPostgres(unittest.TestCase):
    def test_plain_sqlite_con_is_not_postgres(self):
        import sqlite3
        self.assertFalse(db.is_postgres(sqlite3.connect(":memory:")))


if __name__ == "__main__":
    unittest.main()
