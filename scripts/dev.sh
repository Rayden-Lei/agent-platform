#!/usr/bin/env bash
# 一键启动：后端 uvicorn(8000) + 前端 Vite(5173)
#
# 用法：
#   ./scripts/dev.sh            前后端都起（dev 模式，前端有热更新）
#   ./scripts/dev.sh backend    只起后端
#   ./scripts/dev.sh frontend   只起前端
#   ./scripts/dev.sh stop       全停
#   ./scripts/dev.sh status     看状态（含云端地址）
#
# 环境：后端用 ENV_FILE=.env.local（本机这套），前端 Vite 把 ^/api/ 反代到 127.0.0.1:8000。
# 依赖：PG / Redis / MinIO 都在云服务器 47.118.52.252 上，本机经 SSH 隧道访问
#       （15432/16379/19000）。隧道由 launchd 常驻服务维护，不归这个脚本管；
#       连不上先看 launchctl list | grep agent-platform-tunnel。
# 外网：不再用 cloudflared 临时隧道。线上就是云服务器，push 后自动部署：
#       生产 http://47.118.52.252:19080（nginx 托管 dist）
#       开发 http://47.118.52.252:19173（vite dev + HMR）
# 日志：agent-platform/logs/{backend,frontend}.log（已进 .gitignore）
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
PID_DIR="$LOG_DIR/.pids"
mkdir -p "$PID_DIR"

# 云服务器上的对外地址，仅用于 status / 汇总提示
CLOUD_HOST="47.118.52.252"
CLOUD_PROD_PORT="19080"
CLOUD_DEV_PORT="19173"

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

# 依赖服务在云服务器上，本机只能经 SSH 隧道访问。隧道由 launchd 常驻，
# 不归本脚本管；但后端起不来时这是第一个该查的地方，所以先探一下、给一句明确提示，
# 免得看到一堆 connection refused 还以为是代码问题。
check_tunnel() {
  local missing=""
  for p in 15432 16379 19000; do
    nc -z -G 2 127.0.0.1 "$p" 2>/dev/null || missing="$missing $p"
  done
  if [ -n "$missing" ]; then
    c_red "隧道端口未就绪：${missing}"
    c_dim "依赖服务在云服务器上，先恢复 SSH 隧道："
    c_dim "  launchctl kickstart -k gui/$(id -u)/com.lei.agent-platform-tunnel"
    return 1
  fi
}

start_backend() {
  if port_busy "$BE_PORT"; then
    c_dim "后端已在 $BE_PORT 运行，跳过"
    return 0
  fi
  check_tunnel || return 1
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

stop_all() {
  pkill -f "uvicorn app.main:app" 2>/dev/null && c_dim "已停后端"
  # dev 与 preview 两种模式都停：先按端口找，再兜底按命令名
  pkill -f "vite --host 0.0.0.0 --port $FE_PORT" 2>/dev/null
  pkill -f "vite preview --host 0.0.0.0 --port $FE_PORT" 2>/dev/null
  rm -f "$PID_DIR"/*.pid
  c_green "已停止"
}

status_all() {
  local be fe
  be="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:$BE_PORT/health" 2>/dev/null)"
  fe="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:$FE_PORT/" 2>/dev/null)"
  [ "$be" = "200" ] && c_green "后端 $BE_PORT 运行中" || c_red "后端 $BE_PORT 未运行"
  [ "$fe" = "200" ] && c_green "前端 $FE_PORT 运行中" || c_red "前端 $FE_PORT 未运行"
  # 隧道断了两端都会因为连不上库而挂，单独标出来省得去翻日志
  local missing=""
  for p in 15432 16379 19000; do
    nc -z -G 2 127.0.0.1 "$p" 2>/dev/null || missing="$missing $p"
  done
  [ -z "$missing" ] && c_green "依赖隧道正常（15432/16379/19000）" \
                    || c_red "依赖隧道异常：${missing}"
  echo "云端生产  http://${CLOUD_HOST}:${CLOUD_PROD_PORT}"
  echo "云端开发  http://${CLOUD_HOST}:${CLOUD_DEV_PORT}"
}

print_summary() {
  echo
  echo "================================================"
  echo " 前端  http://localhost:$FE_PORT"
  echo " 后端  http://localhost:$BE_PORT/docs"
  echo " 云端  http://${CLOUD_HOST}:${CLOUD_PROD_PORT}（生产）"
  echo "       http://${CLOUD_HOST}:${CLOUD_DEV_PORT}（开发，HMR）"
  echo " 日志  $LOG_DIR/{backend,frontend}.log"
  echo "================================================"
}

case "${1:-all}" in
  stop)     stop_all ;;
  status)   status_all ;;
  backend)  start_backend ;;
  frontend) start_frontend ;;
  all|"")
    start_backend && start_frontend
    print_summary
    ;;
  *)
    c_red "未知参数：$1"; echo "用法：$0 [all|backend|frontend|stop|status]"; exit 1 ;;
esac
