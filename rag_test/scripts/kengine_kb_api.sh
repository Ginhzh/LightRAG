#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/kengine_kb_api.sh query "查询内容" [top_k]
  bash scripts/kengine_kb_api.sh import /path/to/file.md

Environment:
  默认读取仓库根目录 .env；也可通过 ENV_FILE=/path/to/.env 覆盖。

Commands:
  query   调用 EXTERNAL_RAG_URL，用 EXTERNAL_RAG_HEADERS_JSON 中的真实签名/鉴权头。
  import  调用 KENGINE_BASE_URL + KENGINE_IMPORT_PATH，用 KENGINE_IMPORT_HEADERS_JSON
          或 KENGINE_IMPORT_AUTH_TOKEN 中的真实签名/鉴权头。
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

load_env_file() {
  [[ -f "$ENV_FILE" ]] || die "env file not found: $ENV_FILE"
  eval "$("$PYTHON_BIN" - "$ENV_FILE" <<'PY'
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    if line.startswith("export "):
        line = line[len("export "):].strip()
    key, value = line.split("=", 1)
    key = key.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    print(f"export {key}={shlex.quote(value)}")
PY
)"
}

require_env() {
  local name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || die "required env is empty: ${name}"
  done
}

env_bool() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

join_url() {
  local base="${1%/}"
  local path="${2:-}"
  [[ "$path" == /* ]] || path="/${path}"
  printf '%s%s' "$base" "$path"
}

write_curl_headers_config() {
  local mode="$1"
  local output="$2"
  "$PYTHON_BIN" - "$mode" "$output" <<'PY'
from __future__ import annotations

import json
import os
import sys

mode = sys.argv[1]
output = sys.argv[2]

if mode == "query":
    raw = os.getenv("EXTERNAL_RAG_HEADERS_JSON", "{}")
    headers = {}
    default_headers = {"content-type": "application/json"}
    token = ""
elif mode == "import":
    raw = os.getenv("KENGINE_IMPORT_HEADERS_JSON", "{}")
    headers = {"accept": "*/*"}
    default_headers = {}
    token = os.getenv("KENGINE_IMPORT_AUTH_TOKEN", "").strip()
else:
    raise SystemExit(f"unknown header mode: {mode}")

if raw.strip():
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise SystemExit(f"{mode} headers json must be an object")
    headers.update({str(k): str(v) for k, v in parsed.items()})

lower_keys = {key.lower() for key in headers}
for key, value in default_headers.items():
    if key.lower() not in lower_keys:
        headers[key] = value

if token:
    headers["Authorization"] = token

with open(output, "w", encoding="utf-8") as fp:
    for key, value in headers.items():
        if "\n" in key or "\n" in value:
            raise SystemExit("header must not contain newline")
        fp.write(f'header = "{key}: {value}"\n')
PY
}

build_query_payload() {
  local query="$1"
  local user_id="${2:-}"
  local conversation_id="${3:-}"
  "$PYTHON_BIN" - "$query" "$user_id" "$conversation_id" <<'PY'
from __future__ import annotations

import json
import os
import sys

query, user_id, conversation_id = sys.argv[1], sys.argv[2], sys.argv[3]
conversation_id = conversation_id or os.getenv("EXTERNAL_RAG_CONVERSATION_ID", "")

def load_json(name: str, default):
    raw = os.getenv(name, "")
    if not raw:
        return default
    return json.loads(raw)

def render(value, context):
    if isinstance(value, str):
        for key, replacement in context.items():
            value = value.replace("{" + key + "}", replacement)
        return value
    if isinstance(value, list):
        return [render(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render(item, context) for key, item in value.items()}
    return value

template = load_json("EXTERNAL_RAG_REQUEST_TEMPLATE_JSON", None)
if isinstance(template, dict):
    payload = render(
        template,
        {
            "query": query,
            "user_id": user_id,
            "conversation_id": conversation_id,
        },
    )
else:
    payload = {
        "id": "1",
        "content": query,
        "conversationId": conversation_id,
        "model": int(os.getenv("EXTERNAL_RAG_MODEL", "1")),
        "label": "",
        "pluginId": "",
        "questionId": "",
        "tag": "",
        "body": {
            "dataSource": load_json("EXTERNAL_RAG_DATA_SOURCE_JSON", ["knowledge"]),
            "language": os.getenv("EXTERNAL_RAG_LANGUAGE", "cn"),
        },
    }

print(json.dumps(payload, ensure_ascii=False))
PY
}

split_repo_triple() {
  "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import os

triple = os.getenv("KENGINE_REPO_TRIPLE", "").strip()
if triple:
    parts = [item.strip() for item in triple.split("/") if item.strip()]
    if len(parts) != 3:
        raise SystemExit("KENGINE_REPO_TRIPLE must be: spaceGuid/groupGuid/repositoryGuid")
else:
    parts = [
        os.getenv("KENGINE_SPACE_GUID", "").strip(),
        os.getenv("KENGINE_GROUP_GUID", "").strip(),
        os.getenv("KENGINE_REPOSITORY_GUID", "").strip(),
    ]
    if not all(parts):
        raise SystemExit(
            "KENGINE_REPO_TRIPLE or KENGINE_SPACE_GUID/KENGINE_GROUP_GUID/"
            "KENGINE_REPOSITORY_GUID is required"
        )

print("\n".join(parts))
PY
}

run_query() {
  local query="${1:-}"
  local top_k="${2:-5}"
  [[ -n "$query" ]] || die "query text is required"
  require_env EXTERNAL_RAG_URL EXTERNAL_RAG_HEADERS_JSON

  local headers_cfg payload tmp_payload
  headers_cfg="$(mktemp)"
  tmp_payload="$(mktemp)"

  chmod 600 "$headers_cfg" "$tmp_payload"
  write_curl_headers_config query "$headers_cfg"
  payload="$(build_query_payload "$query" "${MEMOS_SYNC_USER_ID:-}" "${EXTERNAL_RAG_CONVERSATION_ID:-}")"
  printf '%s' "$payload" >"$tmp_payload"

  local status=0
  curl --fail-with-body -sS -N \
    -X POST "$EXTERNAL_RAG_URL" \
    --config "$headers_cfg" \
    --data-binary "@${tmp_payload}" || status=$?

  rm -f "$headers_cfg" "$tmp_payload"
  [[ "$status" -eq 0 ]] || return "$status"
  printf '\n'
  printf 'query_done top_k=%s\n' "$top_k" >&2
}

run_import() {
  local file_path="${1:-}"
  [[ -n "$file_path" ]] || die "markdown file path is required"
  [[ -f "$file_path" ]] || die "file not found: $file_path"
  require_env KENGINE_BASE_URL KENGINE_IMPORT_PATH

  local headers_cfg url curl_args
  headers_cfg="$(mktemp)"
  chmod 600 "$headers_cfg"
  write_curl_headers_config import "$headers_cfg"

  mapfile -t repo_parts < <(split_repo_triple)
  [[ "${#repo_parts[@]}" -eq 3 ]] || die "invalid K-Engine repository guid config"

  url="$(join_url "$KENGINE_BASE_URL" "$KENGINE_IMPORT_PATH")"
  curl_args=(
    --fail-with-body
    -sS
    -X POST
    "$url"
    --config "$headers_cfg"
    -F "file=@${file_path};type=text/markdown"
    -F "spaceGuid=${repo_parts[0]}"
    -F "groupGuid=${repo_parts[1]}"
    -F "repositoryGuid=${repo_parts[2]}"
    --max-time "${KENGINE_IMPORT_TIMEOUT_SECONDS:-120}"
  )

  if ! env_bool "${KENGINE_IMPORT_VERIFY_SSL:-true}"; then
    curl_args+=(-k)
  fi

  local status=0
  if curl "${curl_args[@]}"; then
    rm -f "$headers_cfg"
    printf '\n'
    return 0
  fi
  status=$?

  if env_bool "${KENGINE_IMPORT_ALLOW_HTTP_FALLBACK:-false}" && [[ "$url" == https://* ]]; then
    local fallback_url="http://${url#https://}"
    printf 'HTTPS import failed, retrying HTTP fallback: %s\n' "$fallback_url" >&2
    curl_args[4]="$fallback_url"
    curl "${curl_args[@]}" || status=$?
    rm -f "$headers_cfg"
    [[ "$status" -eq 0 ]] || return "$status"
    printf '\n'
    return 0
  fi

  rm -f "$headers_cfg"
  return "$status"
}

main() {
  need_cmd "$PYTHON_BIN"
  need_cmd curl
  load_env_file

  local command="${1:-}"
  shift || true

  case "$command" in
    query)
      run_query "${1:-}" "${2:-5}"
      ;;
    import)
      run_import "${1:-}"
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      usage >&2
      die "unknown command: $command"
      ;;
  esac
}

main "$@"
