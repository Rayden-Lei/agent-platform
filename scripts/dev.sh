#!/usr/bin/env bash
# 一键启动：后端 uvicorn(8000) + 前端 Vite(5173) + 可选外网隧道（cloudflared）
#
# 用法：
#   ./scripts/dev.sh            前后端都起（dev 模式，前端有热更新）
#   ./scripts/dev.sh public     前后端 + 外网隧道，最后打印公网地址
#   ./scripts/dev.sh backend    只起后端
#   ./scripts/dev.sh frontend   只起前端
#   ./scripts/dev.sh tunnel     只起隧道（前后端已在跑时用）
#   ./scripts/dev.sh stop       全停（含隧道）
#   ./scripts/dev.sh status     看状态（含公网地址）
#
# 环境：后端用 ENV_FILE=.env.local（本机这套），前端 Vite 把 ^/api/ 反代到 127.0.0.1:8000。
# 隧道：cloudflared 免费快速隧道，域名每次重启都会变（没有自有域名时无法固定）。
#       前端启动时已放行通配符 .trycloudflare.com，所以域名怎么变都不用改配置。
# 日志：agent-platform/logs/{backend,frontend,tunnel}.log（已进 .gitignore）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BE="$ROOT/backend"
FE="$ROOT/frontend"
BE_PORT="${BE_PORT:-8000}"
FE_PORT="${FE_PORT:-5173}"
# 日志放在项目的 logs/ 下：临时目录会被系统清理，也找不到；logs/ 已进 .gitignore
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
BE_LOG="$LOG_DIR/backend.log"
FE_LOG="$LOG_DIR/frontend.log"
TUNNEL_LOG="$LOG_DIR/tunnel.log"
PID_DIR="$LOG_DIR/.pids"
mkdir -p "$PID_DIR"

# 代理：cloudflared 只认 HTTPS_PROXY 环境变量，不读 macOS 系统代理设置。
# 开着 Clash / Surge 这类工具时，不显式传代理它就连不上 api.trycloudflare.com
# （表现为 "context deadline exceeded"，等 15 秒超时）。
detect_proxy() {
  if [ -n "${HTTPS_PROXY:-}" ] || [ -n "${https_proxy:-}" ]; then
    return 0
  fi
  local host port
  host="$(scutil --proxy 2>/dev/null | awk '/HTTPSProxy/ {print $3}')"
  port="$(scutil --proxy 2>/dev/null | awk '/HTTPSPort/ {print $3}')"
  if [ -n "$host" ] && [ -n "$port" ]; then
    export HTTPS_PROXY="http://$host:$port"
    export HTTP_PROXY="$HTTPS_PROXY"
    c_dim "检测到系统代理 ${host}:${port}，隧道走它"
  fi
}

c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
c_dim()   { printf '\033[2m%s\033[0m\n' "$*"; }

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_http() { # url, 尝试次数（每次 0.5 秒）
  local url="$1" n="${2:-40}" i
  for ((i = 0; i < n; i++)); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' -m 2 "$url" 2>/dev/null)" = "200" ] && return 0
    sleep 0.5
  done
  return 1
}

# 从日志里取公网地址。必须排除 api.trycloudflare.com —— 那是 cloudflared 申请隧道的
# 服务端地址，也会出现在日志里；早期版本没排除，隧道其实失败了却报出一个假地址。
tunnel_url() {
  grep -o 'https://[a-z-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null \
    | grep -v '^https://api\.trycloudflare\.com$' \
    | head -1
}

start_backend() {
  if port_busy "$BE_PORT"; then
    c_dim "后端已在 $BE_PORT 运行，跳过"
    return 0
  fi
  if [ ! -x "$BE/.venv/bin/uvicorn" ]; then
    c_red "找不到 $BE/.venv/bin/uvicorn"
    c_dim "先建虚拟环境：cd backend && uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt"
    return 1
  fi
  echo "==> 启动后端，端口 ${BE_PORT}，ENV_FILE=.env.local"
  (
    cd "$BE" || exit 1
    ENV_FILE=.env.local nohup .venv/bin/uvicorn app.main:app \
      --host 0.0.0.0 --port "$BE_PORT" --reload > "$BE_LOG" 2>&1 &
    echo $! > "$PID_DIR/backend.pid"
  )
  if wait_http "http://127.0.0.1:$BE_PORT/health" 60; then
    c_green "后端就绪：http://localhost:$BE_PORT"
  else
    c_red "后端没起来，日志尾部："
    tail -20 "$BE_LOG"
    return 1
  fi
}

start_frontend() {
  if port_busy "$FE_PORT"; then
    c_dim "前端已在 $FE_PORT 运行，跳过"
    return 0
  fi
  if [ ! -d "$FE/node_modules" ]; then
    c_red "前端依赖没装：cd frontend && npm install"
    return 1
  fi
  echo "==> 启动前端，端口 ${FE_PORT}"
  (
    cd "$FE" || exit 1
    # 放行所有 cloudflared 快速隧道域名：隧道每次重启域名都会变，写死会 403
    VITE_ALLOWED_HOSTS='.trycloudflare.com' \
      nohup npx vite --host 0.0.0.0 --port "$FE_PORT" > "$FE_LOG" 2>&1 &
    echo $! > "$PID_DIR/frontend.pid"
  )
  if wait_http "http://127.0.0.1:$FE_PORT/" 80; then
    c_green "前端就绪：http://localhost:$FE_PORT"
  else
    c_red "前端没起来，日志尾部："
    tail -20 "$FE_LOG"
    return 1
  fi
}

start_tunnel() {
  local existing
  existing="$(tunnel_url)"
  if [ -n "$existing" ] && pgrep -f "cloudflared tunnel --url http://localhost:$FE_PORT" >/dev/null 2>&1; then
    c_dim "隧道已在运行，跳过"
    c_green "公网地址：$existing"
    return 0
  fi
  if ! command -v cloudflared >/dev/null 2>&1; then
    c_red "没装 cloudflared"
    c_dim "brew install cloudflared"
    return 1
  fi
  detect_proxy
  echo "==> 启动外网隧道"
  rm -f "$TUNNEL_LOG"
  nohup cloudflared tunnel --url "http://localhost:$FE_PORT" --no-autoupdate > "$TUNNEL_LOG" 2>&1 &
  echo $! > "$PID_DIR/tunnel.pid"

  local url="" i
  for ((i = 0; i < 60; i++)); do
    url="$(tunnel_url)"
    [ -n "$url" ] && break
    # 申请被拒（常见：Cloudflare API 连不上 / 网络抖动）时不必等满 30 秒
    if grep -q "failed to request quick Tunnel" "$TUNNEL_LOG" 2>/dev/null; then
      c_red "隧道申请失败（Cloudflare API 不可达，稍后重试）："
      grep "failed to request" "$TUNNEL_LOG" | tail -2
      return 1
    fi
    sleep 0.5
  done
  if [ -z "$url" ]; then
    c_red "隧道没起来，日志尾部："
    tail -20 "$TUNNEL_LOG"
    return 1
  fi
  # 首次握手要几秒，等它真能通再报地址
  for ((i = 0; i < 30; i++)); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$url/" 2>/dev/null)" = "200" ] && break
    sleep 1
  done
  c_green "公网地址：$url"
}

stop_all() {
  pkill -f "cloudflared tunnel --url http://localhost:$FE_PORT" 2>/dev/null && c_dim "已停隧道"
  pkill -f "uvicorn app.main:app" 2>/dev/null && c_dim "已停后端"
  # dev 与 preview 两种模式都停：先按端口找，再兜底按命令名
  pkill -f "vite --host 0.0.0.0 --port $FE_PORT" 2>/dev/null
  pkill -f "vite preview --host 0.0.0.0 --port $FE_PORT" 2>/dev/null
  rm -f "$PID_DIR"/*.pid
  c_green "已停止"
}

status_all() {
  local be fe url
  be="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:$BE_PORT/health" 2>/dev/null)"
  fe="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:$FE_PORT/" 2>/dev/null)"
  url="$(tunnel_url)"
  [ "$be" = "200" ] && c_green "后端 $BE_PORT 运行中" || c_red "后端 $BE_PORT 未运行"
  [ "$fe" = "200" ] && c_green "前端 $FE_PORT 运行中" || c_red "前端 $FE_PORT 未运行"
  if [ -n "$url" ] && pgrep -f "cloudflared tunnel --url http://localhost:$FE_PORT" >/dev/null 2>&1; then
    c_green "隧道运行中：$url"
  else
    c_dim "隧道未运行"
  fi
}

print_summary() {
  echo
  echo "================================================"
  echo " 前端  http://localhost:$FE_PORT"
  echo " 后端  http://localhost:$BE_PORT/docs"
  local url; url="$(tunnel_url)"
  [ -n "$url" ] && echo " 公网  $url"
  echo " 日志  $LOG_DIR/{backend,frontend,tunnel}.log"
  echo "================================================"
}

case "${1:-all}" in
  stop)     stop_all ;;
  status)   status_all ;;
  backend)  start_backend ;;
  frontend) start_frontend ;;
  tunnel)   start_tunnel ;;
  public)
    start_backend && start_frontend && start_tunnel
    print_summary
    ;;
  all|"")
    start_backend && start_frontend
    print_summary
    ;;
  *)
    c_red "未知参数：$1"; echo "用法：$0 [all|public|backend|frontend|tunnel|stop|status]"; exit 1 ;;
esac
