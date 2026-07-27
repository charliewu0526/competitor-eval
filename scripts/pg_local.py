#!/usr/bin/env python
"""MR-1b (#51): 起一个真实的本地自托管 Postgres 并暴露 TCP DATABASE_URL.

不依赖 brew/docker —— pgserver 把官方 PostgreSQL 二进制打进 wheel, 纯 pip 装,
数据落本地目录 board/pgdata, 不出本机 (守 ADR-0018: 不用托管云库)。

pgserver 默认只开 unix socket; store.connect_url 走 TCP(urlparse host/port),
故这里用 bundled pg_ctl 以 listen_addresses=127.0.0.1 + 固定端口重启该实例,
再建评测库, 打印可直接喂 store.connect 的 DATABASE_URL。

用法:
  python scripts/pg_local.py start   # 起服务 + 建库, 打印 DATABASE_URL
  python scripts/pg_local.py stop    # 停服务
  python scripts/pg_local.py url     # 只打印 URL (服务须已在跑)
"""
from __future__ import annotations
import os
import subprocess
import sys
import pathlib

import pgserver

ROOT = pathlib.Path(__file__).resolve().parent.parent
PGDATA = ROOT / "board" / "pgdata"
HOST = "127.0.0.1"
PORT = 5433
DBNAME = "competitor_eval"
URL = f"postgresql://postgres@{HOST}:{PORT}/{DBNAME}"


def _bin(name: str) -> str:
    import pgserver as _p
    binroot = pathlib.Path(_p.__file__).resolve().parent / "pginstall" / "bin"
    return str(binroot / name)


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def start() -> str:
    PGDATA.mkdir(parents=True, exist_ok=True)
    # 1) 用 pgserver 完成 initdb + 首次拉起 (它保证 pgdata 初始化好)。
    srv = pgserver.get_server(str(PGDATA))
    # 2) pgserver 那把是 unix-socket only; 停掉它, 用 pg_ctl 以 TCP 重启同一 pgdata。
    _run([_bin("pg_ctl"), "-D", str(PGDATA), "-m", "fast", "stop"])
    opts = f"-c listen_addresses={HOST} -c port={PORT} -c unix_socket_directories='{PGDATA}'"
    logf = PGDATA / "tcp.log"
    r = _run([_bin("pg_ctl"), "-D", str(PGDATA), "-o", opts,
              "-l", str(logf), "-w", "start"])
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr + "\n")
        sys.stderr.write((logf.read_text() if logf.exists() else "") + "\n")
        raise SystemExit(f"pg_ctl start failed rc={r.returncode}")
    # 3) 建评测库 (若不存在)。用 TCP 连默认 postgres 库执行 CREATE DATABASE。
    import pg8000.dbapi as pg
    con = pg.connect(user="postgres", host=HOST, port=PORT, database="postgres")
    con.autocommit = True
    cur = con.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DBNAME,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{DBNAME}"')
    con.close()
    return URL


def stop() -> None:
    _run([_bin("pg_ctl"), "-D", str(PGDATA), "-m", "fast", "stop"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        print(start())
    elif cmd == "stop":
        stop()
        print("stopped")
    elif cmd == "url":
        print(URL)
    else:
        raise SystemExit(f"unknown cmd: {cmd}")
