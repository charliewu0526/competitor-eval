#!/usr/bin/env python
"""MR-1b (#51): 并发领取真穿通 —— SELECT FOR UPDATE 在真 Postgres 上验证.

#37 只在 SQLite 后端验过并发领取; 本脚本用两条**真实独立 PG 连接** + 线程同时抢
同一道 open assignment, 断言恰一人赢, 另一人看到已锁定 (story 10 / #37 AC 在 PG 补齐)。

行锁路径 = store.claim_assignment 的 is_postgres 分支 (SELECT ... FOR UPDATE)。
为逼出真正的行锁竞争 (而非 Python GIL 串行), 我们在两个线程里各开一条连接、
用 barrier 卡到同一时刻再发起 claim。

用: DATABASE_URL=... python scripts/pg_concurrency_check.py
"""
import os
import threading
from pipeline import store, db

url = os.environ["DATABASE_URL"]


def _fresh():
    return store.connect(url=url)


def main():
    setup = _fresh()
    assert db.is_postgres(setup)
    setup.execute("DELETE FROM assignments")
    setup.commit()
    store.upsert_assignment(setup, {"id": "aX", "task_id": "T1",
                                    "products": ["vio", "manus"]})
    setup.close()

    results = {}
    barrier = threading.Barrier(2)

    def worker(name, user):
        con = _fresh()
        barrier.wait()               # 两线程卡齐, 尽量同时发起
        results[name] = store.claim_assignment(con, "aX", user)
        con.close()

    tA = threading.Thread(target=worker, args=("A", "uA"))
    tB = threading.Thread(target=worker, args=("B", "uB"))
    tA.start(); tB.start(); tA.join(); tB.join()

    wins = list(results.values())
    assert wins.count(True) == 1, f"expected exactly 1 winner, got {results}"
    assert wins.count(False) == 1, f"expected exactly 1 loser, got {results}"

    chk = _fresh()
    a = store.get_assignment(chk, "aX")
    assert a["status"] == "claimed"
    winner = "uA" if results["A"] else "uB"
    assert a["claimed_by"] == winner, (a["claimed_by"], winner)
    assert store.open_assignments(chk) == []      # 已不在待领清单
    chk.close()

    print(f"PASS: 并发领取真穿通 —— 恰一人赢 ({results}), "
          f"claimed_by={a['claimed_by']}, SELECT FOR UPDATE 生效")


if __name__ == "__main__":
    main()
