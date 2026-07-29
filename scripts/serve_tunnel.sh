#!/usr/bin/env bash
# launchd 常驻入口: cloudflared 临时隧道(D方案), 暴露本机 8600 到公网 https。
# 由 ~/Library/LaunchAgents/com.competitor-eval.tunnel.plist 拉起, KeepAlive 自愈。
#
# 临时隧道特性: 每次(重)启动 URL 都会变。本脚本把最新 URL 抓出来写到
#   board/public_url.txt   —— 随时 `cat` 它就知道当前发给实习生的链接。
set -uo pipefail
ROOT="/Users/charlie/.violoop/workspace/competitor-eval"
LOG="$ROOT/board/cloudflared.log"
URLFILE="$ROOT/board/public_url.txt"
BIN="$HOME/.local/bin/cloudflared"

export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy 2>/dev/null || true

# 关键: 每次启动前清空旧 URL 文件 + 归零日志。临时隧道每次重启换 URL,
# 若不清, 抓取会命中上一实例已死的僵尸 URL(公网报 Cloudflare 1033)。
: > "$URLFILE"
: > "$LOG"

# 后台抓 URL 写文件(隧道就绪后日志才会出现 trycloudflare.com)。
# 日志已归零, 此时抓到的必是本次进程的 URL。
(
  for _ in $(seq 1 30); do
    u=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | tail -1)
    if [ -n "$u" ]; then echo "$u" > "$URLFILE"; break; fi
    sleep 2
  done
) &

# 前台常驻(exec 让 launchd 直接监管 cloudflared 进程)。
exec "$BIN" tunnel --no-autoupdate --url http://127.0.0.1:8600
