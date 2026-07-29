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

# 归因层(gap_attribution)调 Claude 最强模型需要 CLAUDE_API_KEY。launchd 环境不含
# violoop secrets, 故从本地 env 文件注入(board/backend.env, 600 权限, 已 gitignore)。
if [[ -f "$ROOT/board/backend.env" ]]; then
  set -a; source "$ROOT/board/backend.env"; set +a
fi
# Anthropic 是西方端点, 必须走代理(review_client._needs_proxy 只对西方端点用它);
# localhost 回环由上面的 NO_PROXY 覆盖, 不受影响。仅在 env 提供了代理时恢复。
if [[ -n "${GAP_ATTRIB_HTTPS_PROXY:-}" ]]; then
  export HTTPS_PROXY="$GAP_ATTRIB_HTTPS_PROXY"
  export https_proxy="$GAP_ATTRIB_HTTPS_PROXY"
fi
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# 必须用 violoop venv 的 python(装了 pgserver/pg8000 等依赖);
# 系统 /usr/bin/python3 没有这些包, launchd 默认 PATH 会踩到它。
PY="/Users/charlie/Library/Application Support/violoop/runtime/python/venv/bin/python3"
exec "$PY" "$ROOT/server/run_pg_backend.py"
