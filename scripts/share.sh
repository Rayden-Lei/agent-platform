#!/usr/bin/env bash
# 外网访问：构建 → 起 preview → 起 cloudflared 快速隧道 → 打印地址
#
# 用法：./scripts/share.sh          起服务（默认）
#      ./scripts/share.sh stop     停掉隧道与 preview
#
# 说明：cloudflared 免费快速隧道的域名每次重启都会变（没有自有域名时无法固定），
# 所以 VITE_ALLOWED_HOSTS 只用通配符 *.trycloudflare.com —— 域名怎么变都不用改配置重启。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FE="$ROOT/frontend"
PORT="${PORT:-5173}"
LOG_DIR="${TMPDIR:-/tmp}"
TUNNEL_LOG="$LOG_DIR/agent-platform-tunnel.log"
FE_LOG="$LOG_DIR/agent-platform-preview.log"

stop_all() {
  pkill -f "cloudflared tunnel --url http://localhost:$PORT" 2>/dev/null || true
  pkill -f "vite preview --host 0.0.0.0 --port $PORT" 2>/dev/null || true
  echo "已停止 preview 与隧道"
}

if [ "${1:-}" = "stop" ]; then
  stop_all
  exit 0
fi

stop_all
sleep 1

echo "==> 构建前端"
(cd "$FE" && npx vite build > "$FE_LOG" 2>&1) || { echo "构建失败，日志：$FE_LOG"; tail -20 "$FE_LOG"; exit 1; }

echo "==> 启动 preview，端口 ${PORT}"
(cd "$FE" && VITE_ALLOWED_HOSTS='.trycloudflare.com' \
  nohup npx vite preview --host 0.0.0.0 --port "$PORT" > "$FE_LOG" 2>&1 &)

# 等 preview 起来
for _ in $(seq 1 40); do
  curl -s -o /dev/null -m 1 "http://localhost:$PORT/" && break
  sleep 0.5
done

echo "==> 启动隧道"
rm -f "$TUNNEL_LOG"
nohup cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate > "$TUNNEL_LOG" 2>&1 &

URL=""
for _ in $(seq 1 40); do
  URL="$(grep -o 'https://[a-z-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 0.5
done

if [ -z "$URL" ]; then
  echo "隧道没起来，日志：$TUNNEL_LOG"
  tail -20 "$TUNNEL_LOG"
  exit 1
fi

# 等隧道真正能通（首次握手要几秒）
for _ in $(seq 1 30); do
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$URL/" || echo 000)"
  [ "$code" = "200" ] && break
  sleep 1
done

echo
echo "================================================"
echo " 外网地址：$URL"
echo " 本机地址：http://localhost:$PORT"
echo "================================================"
echo
echo "提示：这个地址在隧道重启后会变。停止：$0 stop"
