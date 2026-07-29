"""MR-1b (#51): 真实 Postgres 穿通集成测 —— #37 地基从「就绪」拉到「跑通」.

#37 只做了方言翻译纯单测(test_db_dialect_mr1)+ SQLite 后端行为测
(test_multiuser_schema_mr1)。本文件把**同一批 store 契约**针对**真实 Postgres
后端**跑一遍(#51 AC「现有 store 测试针对 PG 后端跑一遍, 确认方言翻译无遗漏」)。

自托管、数据不出本地(ADR-0018): 本机无 brew/docker, 用 pgserver(把官方
PostgreSQL 二进制打进 wheel, 纯 pip)起一个 TCP 实例, 见 scripts/pg_local.py。

跳过策略: 环境无 DATABASE_URL(默认 CI / 本机无 PG server)-> 整个模块 skip,
不阻塞 SQLite 全量绿。要跑本测: 先 `python scripts/pg_local.py start` 起本地 PG,
再 `DATABASE_URL=postgresql://postgres@127.0.0.1:5433/competitor_eval \\
     python -m pytest tests/test_postgres_passthrough_mr1b.py -v`。

Run: DATABASE_URL=... python -m unittest tests.test_postgres_passthrough_mr1b -v
"""
from __future__ import annotations
import os
import threading
import unittest

from pipeline import store, db
from pipeline.schema import RunRecord

DATABASE_URL = os.environ.get("DATABASE_URL")
_IS_PG = db.dialect_for(DATABASE_URL) == "postgres"


@unittest.skipUnless(_IS_PG, "no Postgres DATABASE_URL — SQLite backend covers这批契约")
class PostgresPassthrough(unittest.TestCase):
    """同 test_multiuser_schema_mr1 的契约, 打真 PG. 每个用例先清表, 独立可跑."""

    TABLES = ("submissions", "assignments", "methods", "users", "runs",
              "scores", "invites", "sessions", "user_report")

    def _con(self):
        return store.connect(url=DATABASE_URL)

    def setUp(self):
        self.con = self._con()
        self.assertTrue(db.is_postgres(self.con))   # 确认真的在 PG 后端
        for t in self.TABLES:
            self.con.execute(f"DELETE FROM {t}")
        self.con.commit()

    # --- 建表 (方言翻译 DDL 无遗漏) --------------------------------------
    def test_schema_created_on_pg(self):
        # store.connect 已 executescript(translate_ddl(SCHEMA,'postgres')); 表都在.
        for t in self.TABLES:
            n = self.con.execute(f"SELECT count(*) AS c FROM {t}").fetchone()["c"]
            self.assertEqual(n, 0, t)

    # --- User CRUD + RBAC 默认 -----------------------------------------
    def test_user_defaults_intern_and_promote(self):
        store.upsert_user(self.con, {"id": "u1", "name": "Alice"})
        self.assertEqual(store.get_user(self.con, "u1")["role"], "intern")
        store.set_user_role(self.con, "u1", "reviewer")
        self.assertEqual(store.get_user(self.con, "u1")["role"], "reviewer")

    def test_user_upsert_idempotent(self):
        store.upsert_user(self.con, {"id": "u1", "name": "Alice"})
        store.upsert_user(self.con, {"id": "u1", "name": "A B", "role": "owner"})
        self.assertEqual(len(store.all_users(self.con)), 1)
        self.assertEqual(store.get_user(self.con, "u1")["role"], "owner")

    # --- Assignment products JSON round-trip + claim --------------------
    def test_assignment_products_roundtrip(self):
        store.upsert_assignment(self.con, {"id": "a1", "task_id": "T1",
                                           "products": ["vio", "manus", "codebuddy"]})
        a = store.get_assignment(self.con, "a1")
        self.assertEqual(a["products"], ["vio", "manus", "codebuddy"])
        self.assertEqual(a["status"], "open")

    def test_claim_locks_out_second(self):
        store.upsert_assignment(self.con, {"id": "a1", "task_id": "T1",
                                           "products": ["vio"]})
        self.assertTrue(store.claim_assignment(self.con, "a1", "u1"))
        self.assertFalse(store.claim_assignment(self.con, "a1", "u2"))
        a = store.get_assignment(self.con, "a1")
        self.assertEqual(a["status"], "claimed")
        self.assertEqual(a["claimed_by"], "u1")

    def test_abandon_reopens(self):
        store.upsert_assignment(self.con, {"id": "a1", "task_id": "T1",
                                           "products": ["vio"]})
        store.claim_assignment(self.con, "a1", "u1")
        store.set_assignment_status(self.con, "a1", "abandoned")
        a = store.get_assignment(self.con, "a1")
        self.assertEqual(a["status"], "open")
        self.assertIsNone(a["claimed_by"])
        self.assertTrue(store.claim_assignment(self.con, "a1", "u2"))

    def test_concurrent_claim_single_winner_real_rowlock(self):
        """两条真实独立 PG 连接 + 线程同时抢 —— SELECT FOR UPDATE 保证恰一人赢.

        这是 #51 相对 #37 的核心增量: #37 只在 SQLite 串行写者上验过, 这里在
        真 Postgres 行锁上验证 (barrier 卡齐两线程逼出竞争)。
        """
        store.upsert_assignment(self.con, {"id": "aX", "task_id": "T1",
                                           "products": ["vio", "manus"]})
        results: dict[str, bool] = {}
        barrier = threading.Barrier(2)

        def worker(name, user):
            c = self._con()
            barrier.wait()
            results[name] = store.claim_assignment(c, "aX", user)
            c.close()

        ts = [threading.Thread(target=worker, args=a)
              for a in (("A", "uA"), ("B", "uB"))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(list(results.values()).count(True), 1, results)
        self.assertEqual(list(results.values()).count(False), 1, results)
        winner = "uA" if results["A"] else "uB"
        self.assertEqual(store.get_assignment(self.con, "aX")["claimed_by"], winner)

    # --- Submission 路径引用 (库内不存 BLOB) ----------------------------
    def test_submission_paths_not_blobs(self):
        store.upsert_assignment(self.con, {"id": "a1", "task_id": "T1",
                                           "products": ["vio"]})
        sid = store.upsert_submission(self.con, {
            "id": "s1", "assignment_id": "a1", "product": "vio",
            "artifact_path": "/srv/a1/vio/art",
            "log_bundle_path": "/srv/a1/vio/log.zip",
            "manual_assertions": [{"desc": "微信消息真发出了", "checked": True}],
            "claimed_success": True, "submitted_by": "u1"})
        self.assertEqual(sid, "s1")
        s = store.submissions_for(self.con, "a1")[0]
        self.assertEqual(s["log_bundle_path"], "/srv/a1/vio/log.zip")
        self.assertEqual(s["manual_assertions"][0]["checked"], True)
        self.assertEqual(s["claimed_success"], 1)

    def test_one_submission_per_product(self):
        store.upsert_assignment(self.con, {"id": "a1", "task_id": "T1",
                                           "products": ["vio"]})
        store.upsert_submission(self.con, {"id": "s1", "assignment_id": "a1",
                                           "product": "vio", "claimed_success": True})
        store.upsert_submission(self.con, {"id": "s1b", "assignment_id": "a1",
                                           "product": "vio", "claimed_success": False})
        subs = store.submissions_for(self.con, "a1")
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["claimed_success"], 0)

    # --- Method 自增主键 (RETURNING id 跨方言, 曾用 rowid 在 PG 炸) --------
    def test_method_autoincrement_returning(self):
        mid = store.upsert_method(self.con, {"task_id": "T1", "product": "manus",
                                             "draft": "竞品用X, Vio落地Y"})
        self.assertIsInstance(mid, int)
        store.set_method_status(self.con, mid, "approved", gated_by="rv1")
        m = [x for x in store.all_methods(self.con) if x["id"] == mid][0]
        self.assertEqual(m["status"], "approved")
        self.assertEqual(m["gated_by"], "rv1")

    # --- 新鲜度字段 (ADR-0017) -----------------------------------------
    def test_freshness_fields_persist(self):
        rr = RunRecord(task_id="T1", product="manus", run_idx=1,
                       gate="native-operable", competitor_version="build-2026.07",
                       tested_at=1_800_000_000.0, stale=False)
        store.upsert_run(self.con, rr)
        row = self.con.execute("SELECT competitor_version, tested_at, stale "
                               "FROM runs WHERE product=?", ("manus",)).fetchone()
        self.assertEqual(row["competitor_version"], "build-2026.07")
        self.assertEqual(row["tested_at"], 1_800_000_000.0)
        self.assertEqual(row["stale"], 0)

    # --- invite 一次性消费并发 (FOR UPDATE) -----------------------------
    def test_invite_consume_concurrent_single_winner(self):
        store.create_invite(self.con, {"token": "tok1", "note": "x",
                                       "created_by": "owner"})
        self.assertTrue(store.invite_is_valid(self.con, "tok1"))
        results: dict[str, bool] = {}
        barrier = threading.Barrier(2)

        def worker(name, user):
            c = self._con()
            barrier.wait()
            results[name] = store.consume_invite(c, "tok1", user)
            c.close()

        ts = [threading.Thread(target=worker, args=a)
              for a in (("A", "uA"), ("B", "uB"))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(list(results.values()).count(True), 1, results)
        self.assertFalse(store.invite_is_valid(self.con, "tok1"))  # 已被消费

    # --- MR-A (#55) User Report 状态机厚地基针对真 PG 穿通 -----------------
    def test_user_report_thick_schema_and_state_machine_on_pg(self):
        """建表 + 全字段 round-trip + 一条 report 合法流转, 全打真 Postgres.

        AC1/AC2: user_report 表在 PG 方言下真实穿通, 厚字段一次性到位。
        AC3: 合法流转可执行 (策略层守卫与后端无关, 这里验 store 落地 + 守卫原子写)。
        """
        from pipeline import reports as R
        r = R.create(self.con, "u1", "看板白屏", report_id="ur-pg-1")
        self.assertEqual(r["status"], "submitted")
        # 走完 happy path, 顺带写后续票字段 (证明厚列在 PG 可写、无需 migrate)。
        R.enqueue(self.con, "ur-pg-1")
        R.start_ai(self.con, "ur-pg-1", branch_name="fix/ur-pg-1")
        R.mark_patch_ready(self.con, "ur-pg-1", diff_ref="/srv/1.diff",
                           test_result="3 passed")
        row = R.resolve(self.con, "ur-pg-1", good_commit="deadbeef")
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["branch_name"], "fix/ur-pg-1")
        self.assertEqual(row["diff_ref"], "/srv/1.diff")
        self.assertEqual(row["good_commit"], "deadbeef")
        self.assertIsNotNone(row["resolved_ts"])
        R.close(self.con, "ur-pg-1")
        self.assertEqual(store.get_user_report(self.con, "ur-pg-1")["status"],
                         "closed")
        # 非法转移在 PG 后端同样被拒 (fail closed)。
        R.create(self.con, "u1", "另一条", report_id="ur-pg-2")
        with self.assertRaises(R.IllegalTransition):
            R.resolve(self.con, "ur-pg-2")   # submitted 不能直接 resolve

    def tearDown(self):
        self.con.close()


if __name__ == "__main__":
    unittest.main()
