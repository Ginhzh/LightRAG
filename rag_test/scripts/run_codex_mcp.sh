#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${MEMOS_COMPOSE_FILE:-$ROOT_DIR/docker/docker-compose.yml}"
CONTAINER_NAME="${MEMOS_MCP_CONTAINER:-memos-api-docker}"
BASE_URL="${MEMOS_BASE_URL:-http://127.0.0.1:8000}"
DEFAULT_USER_ID="${MEMOS_DEFAULT_USER_ID:-codex-user}"
DEFAULT_MEM_CUBE_ID="${MEMOS_DEFAULT_MEM_CUBE_ID:-default_cube}"
DEFAULT_CONVERSATION_ID="${MEMOS_DEFAULT_CONVERSATION_ID:-codex}"
DEFAULT_SEARCH_SOURCE="${MEMOS_DEFAULT_SEARCH_SOURCE:-external_rag}"
HTTP_TIMEOUT="${MEMOS_MCP_HTTP_TIMEOUT_SECONDS:-90}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found" >&2
  exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "docker compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

if ! docker image inspect "memos-dev-memos:latest" >/dev/null 2>&1; then
  echo "missing image: memos-dev-memos:latest" >&2
  echo "Load /home/wit/docker-image-tars/memos-dev-memos_latest.tar.gz first." >&2
  exit 1
fi

if ! docker image inspect "neo4j:5.26.4" >/dev/null 2>&1; then
  echo "missing image: neo4j:5.26.4" >&2
  echo "Load /home/wit/docker-image-tars/neo4j_5.26.4.tar.gz first." >&2
  exit 1
fi

if ! docker image inspect "qdrant/qdrant:v1.15.3" >/dev/null 2>&1; then
  echo "missing image: qdrant/qdrant:v1.15.3" >&2
  exit 1
fi

docker compose -f "$COMPOSE_FILE" up -d --no-build neo4j qdrant memos >/dev/null

check_ready() {
  docker exec "$CONTAINER_NAME" python - <<'PY' >/dev/null 2>&1
import sys
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/docs", timeout=2) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

for _ in $(seq 1 60); do
  if check_ready; then
    break
  fi
  sleep 1
done

if ! check_ready; then
  echo "MemOS API did not become ready in time." >&2
  docker logs --tail 80 "$CONTAINER_NAME" >&2 || true
  exit 1
fi

exec docker exec -i \
  -e MEMOS_BASE_URL="$BASE_URL" \
  -e MEMOS_DEFAULT_USER_ID="$DEFAULT_USER_ID" \
  -e MEMOS_DEFAULT_MEM_CUBE_ID="$DEFAULT_MEM_CUBE_ID" \
  -e MEMOS_DEFAULT_CONVERSATION_ID="$DEFAULT_CONVERSATION_ID" \
  -e MEMOS_DEFAULT_SEARCH_SOURCE="$DEFAULT_SEARCH_SOURCE" \
  -e MEMOS_MCP_HTTP_TIMEOUT_SECONDS="$HTTP_TIMEOUT" \
  -e MEMOS_API_KEY="${MEMOS_API_KEY:-}" \
  "$CONTAINER_NAME" \
  python -m memos.api.mcp_serve_remote --transport stdio
