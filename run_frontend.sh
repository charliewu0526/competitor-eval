#!/usr/bin/env bash
# One-shot launcher for the competitor-eval product frontend.
#   backend : FastAPI (uvicorn)  -> http://127.0.0.1:8600
#   frontend: Vite dev (bun)     -> http://127.0.0.1:5273
#
# Usage:  ./run_frontend.sh          # start both, open browser
#         ./run_frontend.sh stop     # kill both
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACK_PORT=8600
FRONT_PORT=5273

# Local loopback must bypass any system HTTP proxy, otherwise the Vite dev
# proxy forwards /api requests to the proxy server and returns 502.
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy 2>/dev/null || true

kill_port() { lsof -ti tcp:"$1" 2>/dev/null | xargs -r kill 2>/dev/null || true; }

if [[ "${1:-}" == "stop" ]]; then
  kill_port "$BACK_PORT"; kill_port "$FRONT_PORT"
  echo "stopped backend($BACK_PORT) + frontend($FRONT_PORT)"
  exit 0
fi

# --- backend (自托管 Postgres: 常驻 pgserver + uvicorn, 同进程同生命周期) ---
# PRD-0003/ADR-0018: 生产用自托管 Postgres 支持多人并发领取。run_pg_backend.py 把
# pgserver 与 uvicorn 跑在同一进程, 保证后端连的 socket 不中途消失。数据留本地 board/pgdata。
kill_port "$BACK_PORT"
cd "$ROOT"
CE_BACK_PORT="$BACK_PORT" nohup python3 server/run_pg_backend.py \
  > "$ROOT/board/backend.log" 2>&1 &
echo "backend  -> http://127.0.0.1:$BACK_PORT  (Postgres@board/pgdata, log: board/backend.log)"

# --- frontend ---
kill_port "$FRONT_PORT"
cd "$ROOT/frontend"
[[ -d node_modules ]] || bun install
nohup bun run dev > "$ROOT/board/frontend.log" 2>&1 &
echo "frontend -> http://127.0.0.1:$FRONT_PORT  (log: board/frontend.log)"

sleep 3
command -v open >/dev/null && open "http://127.0.0.1:$FRONT_PORT" || true
echo "opened browser. run './run_frontend.sh stop' to shut down."
