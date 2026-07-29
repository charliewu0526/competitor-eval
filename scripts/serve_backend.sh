#!/usr/bin/env bash
# launchd 常驻入口: 单端口(8600) uvicorn + 自托管 pgserver, serve API + 静态站点。
# 由 ~/Library/LaunchAgents/com.competitor-eval.api.plist 拉起, KeepAlive 崩溃自愈。
set -euo pipefail
ROOT="/Users/charlie/.violoop/workspace/competitor-eval"
cd "$ROOT"

# 本地回环必须绕过系统 HTTP 代理, 否则 localhost 走代理返回 502。
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy 2>/dev/null || true

export CE_BACK_PORT="8600"
export CE_PGDATA="$ROOT/board/pgdata"
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# 必须用 violoop venv 的 python(装了 pgserver/pg8000 等依赖);
# 系统 /usr/bin/python3 没有这些包, launchd 默认 PATH 会踩到它。
PY="/Users/charlie/Library/Application Support/violoop/runtime/python/venv/bin/python3"
exec "$PY" "$ROOT/server/run_pg_backend.py"
