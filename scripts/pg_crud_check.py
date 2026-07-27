#!/usr/bin/env python
"""MR-1b (#51): 真穿通冒烟 —— 四实体 CRUD + 新鲜度字段, 打真 Postgres.

用: DATABASE_URL=... python scripts/pg_crud_check.py
"""
import os
from pipeline import store, db
from pipeline.schema import RunRecord

url = os.environ["DATABASE_URL"]
assert db.dialect_for(url) == "postgres", db.dialect_for(url)
con = store.connect(url=url)
assert db.is_postgres(con)

# 干净起步: 清掉上一轮冒烟遗留 (可重复运行, 不受历史行污染)。
for t in ("submissions", "assignments", "methods", "users", "runs"):
    con.execute(f"DELETE FROM {t}")
con.commit()

store.upsert_user(con, {"id": "u1", "name": "Alice"})
assert store.get_user(con, "u1")["role"] == "intern"
store.set_user_role(con, "u1", "reviewer")
assert store.get_user(con, "u1")["role"] == "reviewer"

store.upsert_assignment(con, {"id": "a1", "task_id": "T1",
                              "products": ["vio", "manus", "codebuddy"]})
a = store.get_assignment(con, "a1")
assert a["products"] == ["vio", "manus", "codebuddy"], a["products"]
assert a["status"] == "open"
assert [x["id"] for x in store.open_assignments(con)] == ["a1"]

sid = store.upsert_submission(con, {
    "id": "s1", "assignment_id": "a1", "product": "vio",
    "artifact_path": "/srv/a1/vio/art", "log_bundle_path": "/srv/a1/vio/log.zip",
    "manual_assertions": [{"desc": "微信消息真发出了", "checked": True}],
    "claimed_success": True, "submitted_by": "u1"})
assert sid == "s1", sid
subs = store.submissions_for(con, "a1")
assert subs[0]["log_bundle_path"] == "/srv/a1/vio/log.zip"
assert subs[0]["manual_assertions"][0]["checked"] is True
assert subs[0]["claimed_success"] == 1

mid = store.upsert_method(con, {"task_id": "T1", "product": "manus",
                                "draft": "竞品用X, Vio落地Y"})
store.set_method_status(con, mid, "approved", gated_by="rv1")
mrow = [x for x in store.all_methods(con) if x["id"] == mid][0]
assert mrow["gated_by"] == "rv1" and mrow["status"] == "approved", mrow

rr = RunRecord(task_id="T1", product="manus", run_idx=1, gate="native-operable",
               competitor_version="build-2026.07", tested_at=1_800_000_000.0,
               stale=False)
store.upsert_run(con, rr)
row = con.execute("SELECT competitor_version,tested_at,stale FROM runs "
                  "WHERE product=?", ("manus",)).fetchone()
assert row["competitor_version"] == "build-2026.07"
assert row["tested_at"] == 1_800_000_000.0
assert row["stale"] == 0

print("PASS: 四实体 CRUD + 新鲜度字段全部穿通真 Postgres 16.2")
print("  method id:", type(mid).__name__, mid)
con.close()
