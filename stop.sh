#!/usr/bin/env bash
# Knowledge OS — 停止所有服务
PIDS_FILE="$(cd "$(dirname "$0")" && pwd)/data/logs/.pids"

if [ ! -f "$PIDS_FILE" ]; then
  echo "没有找到运行记录（$PIDS_FILE），服务可能已经停止。"
  exit 0
fi

echo "正在停止服务..."
while IFS= read -r line; do
  pid=$(echo "$line" | awk '{print $1}')
  name=$(echo "$line" | awk '{$1=""; print $0}' | xargs)
  if kill "$pid" 2>/dev/null; then
    echo "  ✔ $name (PID=$pid) 已停止"
  else
    echo "  - $name (PID=$pid) 已不存在"
  fi
done < "$PIDS_FILE"

rm -f "$PIDS_FILE"
echo "完成。"
