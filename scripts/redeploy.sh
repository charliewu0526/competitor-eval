#!/usr/bin/env bash
# 自动修复/更新接缝: git pull -> 前端 rebuild -> 重启后端 launchd。
# 将来"自动修复门卡"落地就调它。手动也可: bash scripts/redeploy.sh
set -uo pipefail
ROOT="/Users/charlie/.violoop/workspace/competitor-eval"
UID_N="$(id -u)"
cd "$ROOT"

export NO_PROXY="127.0.0.1,localhost"; export no_proxy="127.0.0.1,localhost"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy 2>/dev/null || true
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

# bun 定位: launchd / 精简 PATH 下裸 `bun` 会 command-not-found, 导致前端 build 被
# 静默跳过 -> 假部署(后端更新了、前端 dist 还是旧的)。显式探测绝对路径, 找不到就
# 硬失败(exit 1), 绝不静默跳过 build。
BUN=""
for c in "$HOME/Library/Application Support/violoop/runtime/bun/bin/bun" \
         "$HOME/.bun/bin/bun" "$(command -v bun 2>/dev/null || true)"; do
  [ -x "$c" ] && { BUN="$c"; break; }
done
if [ -z "$BUN" ]; then
  echo "[redeploy] FATAL: 找不到 bun, 无法 build 前端 —— 中止, 避免只更后端的假部署"; exit 1
fi
echo "[redeploy] bun = $BUN"

echo "[redeploy] git pull"
git pull --ff-only 2>&1 | tail -3 || echo "[redeploy] git pull skipped/failed (继续用本地代码)"

echo "[redeploy] frontend build"
( cd frontend && { [ -d node_modules ] || "$BUN" install; }; "$BUN" run build ) 2>&1 | tail -5

echo "[redeploy] restart backend (launchd kickstart)"
launchctl kickstart -k "gui/$UID_N/com.competitor-eval.api" 2>&1 || echo "kickstart rc=$?"

# 隧道不用重启(重启会换 URL); 只有后端换代码需要重载。
sleep 8
echo "[redeploy] health:"
curl -s --noproxy '*' -o /dev/null -w "  local 8600 -> HTTP %{http_code}\n" http://127.0.0.1:8600/ || true
echo "[redeploy] 当前公网链接: $(cat "$ROOT/board/public_url.txt" 2>/dev/null || echo '未知')"
echo "[redeploy] done."
