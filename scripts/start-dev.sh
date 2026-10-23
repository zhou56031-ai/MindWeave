#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if lsof -nP -iTCP:8100 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 8100 已被占用，请先停止旧后端。"
  exit 1
fi
if lsof -nP -iTCP:3100 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 3100 已被占用，请先停止旧前端。"
  exit 1
fi
if pgrep -f "python -m app.graph.worker" >/dev/null 2>&1; then
  echo "图谱 Worker 已在运行，请先停止旧 Worker。"
  exit 1
fi

backend_pid=""
worker_pid=""
front_pid=""

cleanup() {
  for pid in "$front_pid" "$worker_pid" "$backend_pid"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$ROOT/backend"
  exec uv run uvicorn main:app --host 127.0.0.1 --port 8100
) &
backend_pid=$!

(
  cd "$ROOT/backend"
  exec uv run python -m app.graph.worker
) &
worker_pid=$!

(
  cd "$ROOT/front"
  exec npm run dev -- --host 127.0.0.1 --port 3100
) &
front_pid=$!

echo "前端: http://127.0.0.1:3100/"
echo "后端: http://127.0.0.1:8100/"
echo "Worker PID: $worker_pid"
wait
