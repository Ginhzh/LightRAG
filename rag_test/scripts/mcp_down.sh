#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PORT="${MEMOS_PORT:-8000}"
PID_FILE="${MEMOS_PID_FILE:-$ROOT_DIR/.runtime/memos-api.pid}"

find_listener_pid() {
  ss -ltnp "( sport = :$PORT )" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -n 1
}

stopped=0

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Stopped MemOS API by PID file (pid=$PID)"
    stopped=1
  fi
  rm -f "$PID_FILE"
fi

LISTENER_PID="$(find_listener_pid || true)"
if [ -n "${LISTENER_PID:-}" ] && kill -0 "$LISTENER_PID" 2>/dev/null; then
  CMDLINE="$(ps -p "$LISTENER_PID" -o args= || true)"
  if [[ "$CMDLINE" == *"memos.api.server_api:app"* ]]; then
    kill "$LISTENER_PID"
    echo "Stopped residual MemOS API listener (pid=$LISTENER_PID)"
    stopped=1
  fi
fi

if [ "$stopped" -eq 0 ]; then
  echo "No running MemOS API process found."
fi
