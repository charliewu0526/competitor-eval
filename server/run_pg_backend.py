"""生产后端启动器: 常驻 pgserver(自托管 Postgres) + uvicorn。

pgserver 在本进程内 get_server 后, 只要本进程活着 Postgres 就活着 —— 故把 uvicorn
也在本进程 run, 两者同生命周期, 后端连的 socket 不会中途消失(避免服务掉线)。

被 run_frontend.sh 调起。也可独立运行:  python3 server/run_pg_backend.py
环境变量:
  CE_BACK_PORT  后端端口 (默认 8600, 前端 vite proxy 指向它)
  CE_PGDATA     Postgres 数据目录 (默认 <repo>/board/pgdata)
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PGDATA = pathlib.Path(os.environ.get("CE_PGDATA", ROOT / "board" / "pgdata"))
PORT = int(os.environ.get("CE_BACK_PORT", "8600"))

import pgserver

srv = pgserver.get_server(str(PGDATA))
uri = srv.get_uri()
(ROOT / "board" / "pg_uri.txt").write_text(uri)
os.environ["DATABASE_URL"] = uri
print(f"[run_pg_backend] pgserver up (pgdata={PGDATA}):", uri, flush=True)

# 迁移一次(建表 + 补列 + unique index), 之后 web 层每请求 skip_migrate。
from pipeline import store  # noqa: E402

store.connect(url=uri).close()
print("[run_pg_backend] schema migrated", flush=True)

import uvicorn  # noqa: E402

uvicorn.run("server.app:app", host="127.0.0.1", port=PORT, log_level="warning")
