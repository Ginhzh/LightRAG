#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${MEMOS_HOST:-127.0.0.1}"
PORT="${MEMOS_PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
PID_FILE="${MEMOS_PID_FILE:-$ROOT_DIR/.runtime/memos-api.pid}"
LOG_FILE="${MEMOS_LOG_FILE:-$ROOT_DIR/.runtime/memos-api.log}"

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

find_listener_pid() {
  ss -ltnp "( sport = :$PORT )" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -n 1
}

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python not found: $PYTHON_BIN"
  echo "Tip: set PYTHON_BIN or ensure .venv is created."
  exit 1
fi

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"

if curl -fsS "http://$HOST:$PORT/docs" >/dev/null 2>&1; then
  RUNNING_PID="$(find_listener_pid || true)"
  if [ -n "${RUNNING_PID:-}" ]; then
    echo "$RUNNING_PID" > "$PID_FILE"
    echo "MemOS API already running (pid=$RUNNING_PID, http://$HOST:$PORT)"
    exit 0
  fi
fi

if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE")"
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "MemOS API already running (pid=$OLD_PID, http://$HOST:$PORT)"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

MISSING_MODULES=()
for module in jieba pika; do
  if ! "$PYTHON_BIN" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('$module') else 1)"; then
    MISSING_MODULES+=("$module")
  fi
done

if [ "${#MISSING_MODULES[@]}" -gt 0 ]; then
  echo "Installing missing python modules: ${MISSING_MODULES[*]}"
  uv pip install --python "$PYTHON_BIN" "${MISSING_MODULES[@]}"
fi

nohup "$PYTHON_BIN" -m uvicorn memos.api.server_api:app \
  --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
PID="$!"

for _ in $(seq 1 40); do
  if curl -fsS "http://$HOST:$PORT/docs" >/dev/null 2>&1; then
    ACTUAL_PID="$(find_listener_pid || true)"
    if [ -n "${ACTUAL_PID:-}" ]; then
      echo "$ACTUAL_PID" > "$PID_FILE"
      PID="$ACTUAL_PID"
    else
      echo "$PID" > "$PID_FILE"
    fi
    echo "MemOS API is up: http://$HOST:$PORT (pid=$PID)"
    echo "Log file: $LOG_FILE"
    exit 0
  fi
  sleep 1
done

echo "Startup timeout. Check log: $LOG_FILE"
tail -n 80 "$LOG_FILE" || true
exit 1
