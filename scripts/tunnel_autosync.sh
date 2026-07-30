#!/usr/bin/env bash
# tunnel_autosync.sh — 方案B: cloudflared quick-tunnel 公网 URL 自动同步。
#
# 背景: trycloudflare 快速隧道每次(重)启动都换随机域名(本质限制, 无账号也能用)。
# 现有 serve_tunnel.sh(launchd KeepAlive 自愈)已把"当前 URL"写进 board/public_url.txt。
# 本脚本与之解耦, 只负责"URL 变了就广播", 让 owner 不必手动 cat 文件才发现换了链接:
#   - 变化时: 追加带时间戳的历史(board/tunnel_url_history.log)
#   - 变化时: 弹 macOS 桌面通知(新链接 + 旧链接已失效)
#   - 始终: 把最新 URL 也镜像到 board/tunnel_url.txt(稳定文件名, 便于引用)
#
# owner 自己无需隧道: 后端 8600 直接 serve 前端, 本机永久固定入口就是
#   http://127.0.0.1:8600/report-console  —— 隧道 URL 轮换与它无关。
# 公网链接(发实习生用)看 board/public_url.txt, 本脚本保证它永远是最新的。
#
# 用法:  ./tunnel_autosync.sh          # 前台常驻 watch(默认 5s 轮询)
#        ./tunnel_autosync.sh 3        # 自定义轮询秒数
#        ./tunnel_autosync.sh once     # 只同步一次(用于 cron / 手动)
set -uo pipefail
ROOT="/Users/charlie/.violoop/workspace/competitor-eval"
SRC="$ROOT/board/public_url.txt"          # serve_tunnel.sh 写的当前 URL
MIRROR="$ROOT/board/tunnel_url.txt"        # 稳定文件名镜像(引用用)
HIST="$ROOT/board/tunnel_url_history.log"  # 变更历史(带时间戳)

notify() { osascript -e "display notification \"$1\" with title \"竞品评测·公网链接\"" 2>/dev/null || true; }

sync_once() {
  local u last=""
  u="$(cat "$SRC" 2>/dev/null | tr -d '[:space:]')"
  [ -f "$MIRROR" ] && last="$(cat "$MIRROR" 2>/dev/null | tr -d '[:space:]')"
  if [ -n "$u" ] && [ "$u" != "$last" ]; then
    printf '%s\n' "$u" > "$MIRROR"
    printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$u" >> "$HIST"
    notify "新链接: $u(旧链接已失效)"
    echo "[autosync] URL changed -> $u"
    return 0
  fi
  return 1
}

if [ "${1:-}" = "once" ]; then
  sync_once || echo "[autosync] no change (current: $(cat "$MIRROR" 2>/dev/null || echo none))"
  exit 0
fi

INTERVAL="${1:-5}"
echo "[autosync] watching $SRC every ${INTERVAL}s. owner 固定入口: http://127.0.0.1:8600/report-console"
while true; do
  sync_once || true
  sleep "$INTERVAL"
done
