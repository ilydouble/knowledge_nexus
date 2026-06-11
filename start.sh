#!/usr/bin/env bash
# Knowledge OS — 一键启动所有服务
# 用法: ./start.sh [--no-mcp] [--no-web]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$REPO_DIR/data/logs"
CONDA_ENV="nexus"
PIDS_FILE="$LOG_DIR/.pids"

NO_MCP=false
NO_WEB=false
for arg in "$@"; do
  case $arg in
    --no-mcp) NO_MCP=true ;;
    --no-web) NO_WEB=true ;;
  esac
done

mkdir -p "$LOG_DIR"
> "$PIDS_FILE"

# ── 颜色 ──────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✘${NC}  $*"; }

# ── 前置检查 ──────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Knowledge OS — 启动检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for name in kg-postgres kg-neo4j kg-redis; do
  if docker ps --filter "name=$name" --filter "status=running" --format '{{.Names}}' 2>/dev/null | grep -q "$name"; then
    ok "Docker: $name 运行中"
  else
    warn "Docker: $name 未运行（可能影响后端/图谱功能）"
  fi
done

if ! conda run -n "$CONDA_ENV" python --version &>/dev/null; then
  err "conda 环境 '$CONDA_ENV' 不存在，请先执行: conda activate $CONDA_ENV"
  exit 1
fi
ok "Conda 环境: $CONDA_ENV"

# ── 启动函数 ──────────────────────────────────────────────
start_service() {
  local name="$1"; local log="$LOG_DIR/$2.log"; shift 2
  echo ""
  echo "▶ 启动 $name ..."
  # shellcheck disable=SC2068
  "$@" >> "$log" 2>&1 &
  local pid=$!
  echo "$pid $name" >> "$PIDS_FILE"
  ok "$name PID=$pid  日志: data/logs/$(basename "$log")"
}

# ── 各服务 ────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  启动服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cd "$REPO_DIR"

# ① FastAPI 后端
start_service "FastAPI 后端 (8000)" "api" \
  conda run -n "$CONDA_ENV" uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# ② Worker
start_service "Worker" "worker" \
  conda run -n "$CONDA_ENV" python -m apps.worker.main

# ③ Web 控制台
if [ "$NO_WEB" = false ]; then
  if command -v npm &>/dev/null; then
    (cd "$REPO_DIR/apps/web" && npm run dev >> "$LOG_DIR/web.log" 2>&1) &
    WEB_PID=$!
    echo "$WEB_PID Web控制台" >> "$PIDS_FILE"
    ok "Web 控制台 PID=$WEB_PID  日志: data/logs/web.log"
  else
    warn "npm 未找到，跳过 Web 控制台"
  fi
fi

# ④ MCP Server（可选）
if [ "$NO_MCP" = false ]; then
  start_service "MCP Server" "mcp" \
    conda run -n "$CONDA_ENV" python -m apps.mcp.server
fi

# ── 汇总 ──────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  服务地址"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  API   → http://localhost:8000"
[ "$NO_WEB" = false ] && echo "  Web   → http://localhost:5173"
echo "  日志  → $LOG_DIR/"
echo ""
echo "停止所有服务: ./stop.sh"
echo ""

# ── 等待（Ctrl-C 清理） ────────────────────────────────────
trap 'echo ""; echo "正在关闭..."; kill $(awk "{print \$1}" "$PIDS_FILE") 2>/dev/null; exit 0' INT TERM
wait
