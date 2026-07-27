"""MR-1 (#37): 多人评测工场地基 — 四实体建表读写 + 并发领取锁 + 新鲜度字段.

Run: python -m unittest tests.test_multiuser_schema_mr1 -v

Acceptance (issue #37):
  - User/Assignment/Submission/Method 四实体建表 + round-trip
  - RunRecord/score 增 competitor_version / tested_at / stale (ADR-0017)
  - 并发领取: 两请求抢同一 open assignment, 仅一成功 (SELECT FOR UPDATE / UNIQUE)
  - 文件走路径引用, 库内不存二进制
  - 评分核心零改动 (仅新增地基, 现有 310 测试作回归护栏)
"""
from __future__ import annotations
import tempfile
import pathlib
import unittest
from pipeline import store
from pipeline.schema import RunRecord


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


class UsersRBAC(unittest.TestCase):
    def test_user_defaults_intern(self):
        con = store.connect(_tmpdb())
        store.upsert_user(con, {"id": "u1", "name": "Alice"})
        u = store.get_user(con, "u1")
        self.assertEqual(u["role"], "intern")           # 默认最小权限 (ADR-0014)

    def test_promote_to_reviewer(self):
        con = store.connect(_tmpdb())
        store.upsert_user(con, {"id": "u1", "name": "Alice"})
        store.set_user_role(con, "u1", "reviewer")
        self.assertEqual(store.get_user(con, "u1")["role"], "reviewer")

    def test_upsert_idempotent(self):
        con = store.connect(_tmpdb())
        store.upsert_user(con, {"id": "u1", "name": "Alice"})
        store.upsert_user(con, {"id": "u1", "name": "Alice B", "role": "owner"})
        self.assertEqual(len(store.all_users(con)), 1)   # updated, not duplicated
        self.assertEqual(store.get_user(con, "u1")["role"], "owner")


class AssignmentClaim(unittest.TestCase):
    def _seed(self, con):
        store.upsert_assignment(con, {"id": "a1", "task_id": "T1",
                                      "products": ["vio", "manus", "codebuddy"]})

    def test_products_roundtrip(self):
        con = store.connect(_tmpdb())
        self._seed(con)
        a = store.get_assignment(con, "a1")
        self.assertEqual(a["products"], ["vio", "manus", "codebuddy"])
        self.assertEqual(a["status"], "open")

    def test_open_lists_only_open(self):
        con = store.connect(_tmpdb())
        self._seed(con)
        self.assertEqual([a["id"] for a in store.open_assignments(con)], ["a1"])
        store.claim_assignment(con, "a1", "u1")
        self.assertEqual(store.open_assignments(con), [])

    def test_claim_locks_out_second_runner(self):
        # 并发领取控制 (story 10): 两个 runner 抢同一道 open, 只有一个赢.
        con = store.connect(_tmpdb())
        self._seed(con)
        first = store.claim_assignment(con, "a1", "u1")
        second = store.claim_assignment(con, "a1", "u2")   # already claimed
        self.assertTrue(first)
        self.assertFalse(second)
        a = store.get_assignment(con, "a1")
        self.assertEqual(a["status"], "claimed")
        self.assertEqual(a["claimed_by"], "u1")            # 第一个人保住

    def test_abandon_reopens(self):
        # 领了没做的题回到清单 (story 12).
        con = store.connect(_tmpdb())
        self._seed(con)
        store.claim_assignment(con, "a1", "u1")
        store.set_assignment_status(con, "a1", "abandoned")
        a = store.get_assignment(con, "a1")
        self.assertEqual(a["status"], "open")
        self.assertIsNone(a["claimed_by"])
        self.assertTrue(store.claim_assignment(con, "a1", "u2"))  # 别人可再领

    def test_concurrent_claims_single_winner(self):
        # 用两条独立连接模拟并发写者; SQLite 串行化写, 只有一条 UPDATE 命中 open 行.
        path = _tmpdb()
        con0 = store.connect(path)
        self._seed(con0)
        conA = store.connect(path)
        conB = store.connect(path)
        wins = [store.claim_assignment(conA, "a1", "uA"),
                store.claim_assignment(conB, "a1", "uB")]
        self.assertEqual(wins.count(True), 1)              # 恰一人成功
        self.assertEqual(wins.count(False), 1)


class SubmissionFileRefs(unittest.TestCase):
    def test_submission_stores_paths_not_blobs(self):
        # 文件走服务端目录, 库内只存路径引用 (ADR-0019, #37 AC).
        con = store.connect(_tmpdb())
        store.upsert_assignment(con, {"id": "a1", "task_id": "T1",
                                      "products": ["vio", "manus"]})
        sid = store.upsert_submission(con, {
            "id": "s1", "assignment_id": "a1", "product": "vio",
            "artifact_path": "/srv/eval/a1/vio/artifacts",
            "log_bundle_path": "/srv/eval/a1/vio/log_bundle.zip",
            "manual_assertions": [{"desc": "微信消息真发出了", "checked": True}],
            "claimed_success": True, "submitted_by": "u1"})
        self.assertEqual(sid, "s1")
        subs = store.submissions_for(con, "a1")
        self.assertEqual(len(subs), 1)
        s = subs[0]
        self.assertEqual(s["log_bundle_path"], "/srv/eval/a1/vio/log_bundle.zip")
        self.assertEqual(s["manual_assertions"][0]["checked"], True)
        self.assertEqual(s["claimed_success"], 1)
        # no BLOB columns anywhere in submissions
        types = {r[1]: r[2] for r in con.execute("PRAGMA table_info(submissions)")}
        self.assertNotIn("BLOB", {t.upper() for t in types.values()})

    def test_one_submission_per_product(self):
        con = store.connect(_tmpdb())
        store.upsert_assignment(con, {"id": "a1", "task_id": "T1",
                                      "products": ["vio"]})
        store.upsert_submission(con, {"id": "s1", "assignment_id": "a1",
                                      "product": "vio", "claimed_success": True})
        store.upsert_submission(con, {"id": "s1b", "assignment_id": "a1",
                                      "product": "vio", "claimed_success": False})
        subs = store.submissions_for(con, "a1")
        self.assertEqual(len(subs), 1)                     # upsert on (assign,product)
        self.assertEqual(subs[0]["claimed_success"], 0)    # updated


class MethodGate(unittest.TestCase):
    def test_method_draft_to_exported(self):
        con = store.connect(_tmpdb())
        mid = store.upsert_method(con, {"task_id": "T1", "product": "manus",
                                        "draft": "竞品用了 X 手法, Violoop 可落地 Y"})
        self.assertIsInstance(mid, int)
        self.assertEqual(store.all_methods(con, status="draft")[0]["id"], mid)
        # 方法复核闸: reviewer 把关
        store.set_method_status(con, mid, "approved", gated_by="rv1")
        store.set_method_status(con, mid, "exported")
        m = store.all_methods(con)[0]
        self.assertEqual(m["status"], "exported")
        self.assertEqual(m["gated_by"], "rv1")             # gated_by 保住


class FreshnessFields(unittest.TestCase):
    def test_runrecord_freshness_persists(self):
        # ADR-0017: 每条分数绑竞品版本 + 测试日期, 超期标陈旧.
        con = store.connect(_tmpdb())
        rr = RunRecord(task_id="T1", product="manus", run_idx=1,
                       gate="native-operable", competitor_version="build-2026.07",
                       tested_at=1_800_000_000.0, stale=False)
        store.upsert_run(con, rr)
        row = con.execute("SELECT competitor_version, tested_at, stale FROM runs "
                          "WHERE product='manus'").fetchone()
        self.assertEqual(row["competitor_version"], "build-2026.07")
        self.assertEqual(row["tested_at"], 1_800_000_000.0)
        self.assertEqual(row["stale"], 0)

    def test_score_freshness_persists(self):
        con = store.connect(_tmpdb())
        store.upsert_score(con, {"task_id": "T1", "product": "manus", "run_idx": 1,
                                 "gate": "native-operable", "sample_score": 0.7,
                                 "competitor_version": "v2", "tested_at": 1_700_000_000.0,
                                 "stale": True})
        row = con.execute("SELECT competitor_version, stale FROM scores "
                          "WHERE product='manus'").fetchone()
        self.assertEqual(row["competitor_version"], "v2")
        self.assertEqual(row["stale"], 1)

    def test_freshness_defaults_backcompat(self):
        # 不带新鲜度字段的老 score dict 仍能写 (pipeline 零改动护栏).
        con = store.connect(_tmpdb())
        store.upsert_score(con, {"task_id": "T1", "product": "vio", "run_idx": 1,
                                 "gate": "native-operable", "sample_score": 0.9})
        row = con.execute("SELECT competitor_version, stale FROM scores "
                          "WHERE product='vio'").fetchone()
        self.assertIsNone(row["competitor_version"])
        self.assertEqual(row["stale"], 0)


if __name__ == "__main__":
    unittest.main()
