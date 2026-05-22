#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${MEMOS_HOST:-127.0.0.1}"
PORT="${MEMOS_PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
BASE_URL="http://$HOST:$PORT"

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python not found: $PYTHON_BIN"
  exit 1
fi

if ! curl -fsS "$BASE_URL/docs" >/dev/null 2>&1; then
  echo "Health check failed: $BASE_URL/docs is unreachable."
  echo "Run: scripts/mcp_up.sh"
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

host = os.getenv("MEMOS_HOST", "127.0.0.1")
port = os.getenv("MEMOS_PORT", "8000")
mem_cube_id = os.getenv("MEMOS_MEM_CUBE_ID", "default_cube")
base = f"http://{host}:{port}"


def post(path: str, payload: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310
            return resp.status, resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return e.code, body
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


checks = [
    ("/product/search", {"query": "mcp health check", "top_k": 1, "user_id": "codex-user"}),
    (
        "/product/get_memory",
        {"user_id": "codex-user", "mem_cube_id": mem_cube_id, "page": 1, "size": 1},
    ),
]

failed = False
for path, payload in checks:
    code, body = post(path, payload)
    preview = body[:200].replace("\n", " ")
    print(f"{path}: HTTP {code} | {preview}")
    if code != 200:
        failed = True

if failed:
    sys.exit(1)
PY

echo "MCP backend health check passed."
