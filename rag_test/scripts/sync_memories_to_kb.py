#!/usr/bin/env python3
"""
Sync memories from MemOS to external knowledge base (K-Engine).

Usage:
  python scripts/sync_memories_to_kb.py --mode incremental
  python scripts/sync_memories_to_kb.py --mode full
  python scripts/sync_memories_to_kb.py --mode incremental --memory-id <id>
  python scripts/sync_memories_to_kb.py --mode incremental --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional runtime dependency
    def load_dotenv() -> None:
        for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"):
            if not candidate.exists():
                continue
            for raw_line in candidate.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key or key in os.environ:
                    continue
                if " #" in value:
                    value = value.split(" #", 1)[0].rstrip()
                os.environ[key] = value
            break


logger = logging.getLogger("memory-kb-sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
load_dotenv()


@dataclass
class MemoryRecord:
    sync_id: str
    memory_id: str
    cube_id: str
    memory_type: str
    content: str
    metadata: dict[str, Any]
    created_at: str


@dataclass
class ExportBatch:
    file_path: Path
    sync_ids: list[str]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int env %s=%s, fallback=%s", name, raw, default)
        return default


def _slug(value: str, max_len: int = 48) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    normalized = normalized.strip("._-") or "unknown"
    return normalized[:max_len]


def _base_url() -> str:
    return os.getenv("MEMOS_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")


def _api_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("MEMOS_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Token {api_key}"
    return headers


def _sync_user_id() -> str:
    return os.getenv("MEMORY_SYNC_USER_ID", "").strip() or os.getenv("MEMOS_DEFAULT_USER_ID", "").strip()


def _sync_mem_cube_id(user_id: str) -> str:
    return (
        os.getenv("MEMORY_SYNC_MEM_CUBE_ID", "").strip()
        or os.getenv("MEMOS_DEFAULT_MEM_CUBE_ID", "").strip()
        or user_id
    )


def _state_path() -> Path:
    return Path(os.getenv("MEMORY_SYNC_STATE_PATH", ".memos/memory_sync_state.json"))


def _load_state() -> set[str]:
    path = _state_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        synced_ids = data.get("synced_ids", [])
        if isinstance(synced_ids, list):
            return {str(item) for item in synced_ids if str(item).strip()}
    except Exception:
        logger.warning("Failed to load state file: %s", path)
    return set()


def _save_state(synced_ids: set[str]) -> None:
    max_items = _env_int("MEMORY_SYNC_MAX_STATE_IDS", 50000)
    state_items = list(synced_ids)
    if len(state_items) > max_items:
        state_items = state_items[-max_items:]

    payload = {
        "synced_ids": state_items,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _post(path: str, payload: Any) -> dict[str, Any]:
    timeout_seconds = _env_int("MEMORY_SYNC_TIMEOUT_SECONDS", 30)
    url = f"{_base_url()}{path}"
    response = requests.post(
        url,
        data=json.dumps(payload, ensure_ascii=False),
        headers=_api_headers(),
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        body = response.text[:500] if response.text else ""
        raise RuntimeError(f"HTTP {response.status_code} calling {path}: {body}")
    parsed = response.json()
    if isinstance(parsed, dict):
        return parsed
    return {"data": parsed}


def _record_sync_id(memory: dict[str, Any]) -> tuple[str, str]:
    memory_id = str(memory.get("id") or memory.get("memory_id") or "").strip()
    if memory_id:
        return memory_id, memory_id

    raw = json.dumps(memory, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return fingerprint, ""


def _memory_text(memory: dict[str, Any]) -> str:
    for key in ("memory", "content", "text", "message"):
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(memory, ensure_ascii=False)


def _memory_created_at(memory: dict[str, Any]) -> str:
    for key in ("created_at", "timestamp", "createdAt"):
        value = memory.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1_000_000_000_000:
                ts /= 1000.0
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                continue
    return datetime.now(timezone.utc).isoformat()


def _memory_type(memory: dict[str, Any], bucket_name: str) -> str:
    metadata = memory.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("type")
        if isinstance(value, str) and value.strip():
            return value.strip()

    value = memory.get("memory_type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return bucket_name


def _normalize_memory_record(
    memory: Any, *, cube_id: str, bucket_name: str
) -> MemoryRecord | None:
    if not isinstance(memory, dict):
        return None

    metadata = memory.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    sync_id, memory_id = _record_sync_id(memory)
    return MemoryRecord(
        sync_id=sync_id,
        memory_id=memory_id,
        cube_id=cube_id,
        memory_type=_memory_type(memory, bucket_name),
        content=_memory_text(memory),
        metadata=metadata,
        created_at=_memory_created_at(memory),
    )


def _dedupe_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    deduped: list[MemoryRecord] = []
    seen: set[str] = set()
    for item in records:
        if item.sync_id in seen:
            continue
        seen.add(item.sync_id)
        deduped.append(item)
    return deduped


def _extract_records_from_get_memory(
    data: Any, default_cube_id: str, include_preference: bool
) -> list[MemoryRecord]:
    if not isinstance(data, dict):
        return []

    bucket_names = ["text_mem"]
    if include_preference:
        bucket_names.append("pref_mem")

    records: list[MemoryRecord] = []
    for bucket_name in bucket_names:
        groups = data.get(bucket_name, [])
        if not isinstance(groups, list):
            continue

        for group in groups:
            if not isinstance(group, dict):
                continue
            cube_id = str(group.get("cube_id") or default_cube_id).strip() or default_cube_id
            memories = group.get("memories", [])
            if not isinstance(memories, list):
                continue

            for memory in memories:
                record = _normalize_memory_record(
                    memory, cube_id=cube_id, bucket_name=bucket_name
                )
                if record is not None:
                    records.append(record)

    return _dedupe_records(records)


def _extract_records_from_get_memory_by_ids(
    data: Any, default_cube_id: str
) -> list[MemoryRecord]:
    if not isinstance(data, dict):
        return []
    memories = data.get("memories", [])
    if not isinstance(memories, list):
        return []

    records: list[MemoryRecord] = []
    for memory in memories:
        cube_id = default_cube_id
        if isinstance(memory, dict):
            metadata = memory.get("metadata")
            if isinstance(metadata, dict):
                cube_id = str(metadata.get("user_name") or default_cube_id).strip() or default_cube_id
        record = _normalize_memory_record(memory, cube_id=cube_id, bucket_name="memory")
        if record is not None:
            records.append(record)
    return _dedupe_records(records)


def _fetch_memory_records(
    *,
    user_id: str,
    mem_cube_id: str,
    include_preference: bool,
    memory_ids: list[str],
) -> list[MemoryRecord]:
    if memory_ids:
        response = _post("/product/get_memory_by_ids", memory_ids)
        return _extract_records_from_get_memory_by_ids(response.get("data"), mem_cube_id)

    payload = {
        "user_id": user_id,
        "mem_cube_id": mem_cube_id,
        "include_preference": include_preference,
        "include_tool_memory": False,
        "include_skill_memory": False,
        "page": None,
        "page_size": None,
    }
    response = _post("/product/get_memory", payload)
    return _extract_records_from_get_memory(response.get("data"), mem_cube_id, include_preference)


def _kengine_guids() -> tuple[str, str, str]:
    triple = os.getenv("KENGINE_REPO_TRIPLE", "").strip()
    if triple:
        parts = [item.strip() for item in triple.split("/") if item.strip()]
        if len(parts) != 3:
            raise ValueError("KENGINE_REPO_TRIPLE must be: spaceGuid/groupGuid/repositoryGuid")
        return parts[0], parts[1], parts[2]

    space_guid = os.getenv("KENGINE_SPACE_GUID", "").strip()
    group_guid = os.getenv("KENGINE_GROUP_GUID", "").strip()
    repository_guid = os.getenv("KENGINE_REPOSITORY_GUID", "").strip()
    if not (space_guid and group_guid and repository_guid):
        raise ValueError(
            "KENGINE_SPACE_GUID, KENGINE_GROUP_GUID, KENGINE_REPOSITORY_GUID are required"
        )
    return space_guid, group_guid, repository_guid


def _kengine_import_url() -> str:
    base_url = os.getenv("KENGINE_BASE_URL", "https://k-engine.weichai.com").strip().rstrip("/")
    import_path = os.getenv(
        "KENGINE_IMPORT_PATH", "/path_wiki/wiki/ku/openapi/files/import"
    ).strip()
    if not import_path.startswith("/"):
        import_path = "/" + import_path
    return base_url + import_path


def _upload_file_to_kengine(file_path: Path) -> bool:
    space_guid, group_guid, repository_guid = _kengine_guids()
    url = _kengine_import_url()
    timeout_seconds = _env_int("KENGINE_IMPORT_TIMEOUT_SECONDS", 120)
    verify_ssl = _env_bool("KENGINE_IMPORT_VERIFY_SSL", True)
    allow_http_fallback = _env_bool("KENGINE_IMPORT_ALLOW_HTTP_FALLBACK", False)

    headers = {"accept": "*/*"}
    headers_extra = os.getenv("KENGINE_IMPORT_HEADERS_JSON", "").strip()
    if headers_extra:
        try:
            parsed = json.loads(headers_extra)
            if isinstance(parsed, dict):
                headers.update(parsed)
        except json.JSONDecodeError:
            logger.warning("Invalid KENGINE_IMPORT_HEADERS_JSON, ignore extra headers.")

    auth_token = os.getenv("KENGINE_IMPORT_AUTH_TOKEN", "").strip()
    if auth_token:
        headers["Authorization"] = auth_token

    files_data = {
        "spaceGuid": space_guid,
        "groupGuid": group_guid,
        "repositoryGuid": repository_guid,
    }

    def _post_once(target_url: str):
        with file_path.open("rb") as fp:
            files = {"file": (file_path.name, fp, "text/markdown")}
            return requests.post(
                url=target_url,
                headers=headers,
                files=files,
                data=files_data,
                timeout=timeout_seconds,
                verify=verify_ssl,
            )

    try:
        response = _post_once(url)
    except requests.exceptions.SSLError:
        if allow_http_fallback and url.startswith("https://"):
            fallback_url = "http://" + url[len("https://") :]
            logger.warning(
                "HTTPS upload failed for %s, retrying with HTTP fallback %s",
                url,
                fallback_url,
            )
            try:
                response = _post_once(fallback_url)
            except requests.exceptions.RequestException as exc:
                logger.error("K-Engine fallback import failed for %s: %s", file_path.name, exc)
                return False
        else:
            raise
    except requests.exceptions.RequestException as exc:
        logger.error("K-Engine import request failed for %s: %s", file_path.name, exc)
        return False

    body = response.text or ""
    content_type = (response.headers.get("content-type") or "").lower()
    if response.status_code >= 400:
        logger.error("K-Engine import failed (%s): %s", response.status_code, body)
        return False

    if "text/html" in content_type and (
        "<!doctype html" in body.lower() or "登录-潍柴知识管理平台" in body
    ):
        logger.error(
            "K-Engine import failed: received login HTML page "
            "(authentication likely missing/expired)."
        )
        return False

    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            if parsed.get("success") is False:
                logger.error("K-Engine import failed (success=false): %s", parsed)
                return False
            code = parsed.get("code")
            if code is not None and str(code) not in {"0", "200"}:
                logger.error("K-Engine import may have failed (code=%s): %s", code, parsed)
                return False
    except ValueError:
        pass

    logger.info("K-Engine import succeeded for %s", file_path.name)
    return True


def _render_batch_markdown(records: list[MemoryRecord], user_id: str, mem_cube_id: str) -> str:
    lines = [
        "# Memory Sync Export",
        "",
        f"- exported_at: {datetime.now(timezone.utc).isoformat()}",
        f"- user_id: {user_id}",
        f"- mem_cube_id: {mem_cube_id}",
        f"- record_count: {len(records)}",
        "",
    ]
    max_chars = _env_int("MEMORY_SYNC_MAX_CONTENT_CHARS", 20000)

    for idx, record in enumerate(records, start=1):
        content = record.content.strip()
        if len(content) > max_chars:
            content = content[:max_chars].rstrip() + "\n\n[TRUNCATED]\n"

        lines.extend(
            [
                f"## {idx}. {record.memory_id or record.sync_id}",
                "",
                f"- cube_id: {record.cube_id}",
                f"- memory_type: {record.memory_type}",
                f"- created_at: {record.created_at}",
                "",
                "### Content",
                "",
                content or "(empty)",
                "",
                "### Metadata",
                "",
                "```json",
                json.dumps(record.metadata, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def _write_exports(
    records: list[MemoryRecord], *, user_id: str, mem_cube_id: str
) -> list[ExportBatch]:
    export_dir = Path(os.getenv("MEMORY_SYNC_EXPORT_DIR", ".memos/memory_kb_exports"))
    export_dir.mkdir(parents=True, exist_ok=True)

    max_records_per_file = max(1, _env_int("MEMORY_SYNC_MAX_RECORDS_PER_FILE", 200))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    user_slug = _slug(user_id)
    cube_slug = _slug(mem_cube_id)

    batches: list[ExportBatch] = []
    for index, start in enumerate(range(0, len(records), max_records_per_file), start=1):
        chunk = records[start : start + max_records_per_file]
        file_name = f"memory_sync_{timestamp}_{user_slug}_{cube_slug}_{index:04d}.md"
        file_path = export_dir / file_name
        file_path.write_text(
            _render_batch_markdown(chunk, user_id=user_id, mem_cube_id=mem_cube_id),
            encoding="utf-8",
        )
        batches.append(ExportBatch(file_path=file_path, sync_ids=[item.sync_id for item in chunk]))
    return batches


def _import_records_to_kengine(
    records: list[MemoryRecord], *, user_id: str, mem_cube_id: str
) -> set[str]:
    batches = _write_exports(records, user_id=user_id, mem_cube_id=mem_cube_id)
    if not batches:
        return set()

    logger.info("Prepared %s markdown files for memory sync", len(batches))
    success_ids: set[str] = set()
    for batch in batches:
        if _upload_file_to_kengine(batch.file_path):
            success_ids.update(batch.sync_ids)
    return success_ids


def _summarize_records(records: list[MemoryRecord]) -> None:
    if not records:
        logger.info("No records fetched from MemOS get_memory APIs.")
        return

    type_counter: dict[str, int] = {}
    cube_counter: dict[str, int] = {}
    for record in records:
        type_counter[record.memory_type] = type_counter.get(record.memory_type, 0) + 1
        cube_counter[record.cube_id] = cube_counter.get(record.cube_id, 0) + 1

    type_summary = ", ".join(f"{k}={v}" for k, v in sorted(type_counter.items()))
    cube_summary = ", ".join(f"{k}={v}" for k, v in sorted(cube_counter.items()))
    logger.info(
        "Fetched records summary: total=%s, by_type=(%s), by_cube=(%s)",
        len(records),
        type_summary,
        cube_summary,
    )


def run_once(
    *,
    mode: str,
    dry_run: bool,
    memory_ids: list[str],
    include_preference: bool,
) -> None:
    user_id = _sync_user_id()
    if not user_id:
        raise ValueError("MEMORY_SYNC_USER_ID or MEMOS_DEFAULT_USER_ID is required")
    mem_cube_id = _sync_mem_cube_id(user_id)

    fetched_records = _fetch_memory_records(
        user_id=user_id,
        mem_cube_id=mem_cube_id,
        include_preference=include_preference,
        memory_ids=memory_ids,
    )
    _summarize_records(fetched_records)

    if not fetched_records:
        logger.info("Memory sync done. mode=%s success=0 skipped=0 failed=0", mode)
        return

    seen = _load_state()
    skipped = 0

    if memory_ids:
        # Explicit IDs are treated as "sync now" payload.
        candidate_records = fetched_records
    elif mode == "full":
        candidate_records = fetched_records
    else:
        candidate_records = [item for item in fetched_records if item.sync_id not in seen]
        skipped = len(fetched_records) - len(candidate_records)

    logger.info("New items: %s", len(candidate_records))

    if not candidate_records:
        logger.info("Memory sync done. mode=%s success=0 skipped=%s failed=0", mode, skipped)
        return

    if dry_run:
        logger.info("Dry-run mode enabled. No upload executed, state file unchanged.")
        return

    sink = os.getenv("MEMORY_SYNC_SINK", "kengine").strip().lower()
    success = 0
    failed = 0

    if sink in {"kengine", "kengine_file", "k-engine"}:
        success_ids = _import_records_to_kengine(
            candidate_records, user_id=user_id, mem_cube_id=mem_cube_id
        )
        success = len(success_ids)
        failed = len(candidate_records) - success
        seen.update(success_ids)
    else:
        raise ValueError("MEMORY_SYNC_SINK must be one of: kengine")

    _save_state(seen)
    logger.info("Memory sync done. mode=%s success=%s skipped=%s failed=%s", mode, success, skipped, failed)


def _parse_memory_ids(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    for item in args.memory_id:
        value = str(item).strip()
        if value:
            values.append(value)

    if args.memory_ids:
        for item in str(args.memory_ids).split(","):
            value = item.strip()
            if value:
                values.append(value)

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync MemOS memories to external knowledge base")
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="incremental = sync unsynced records only; full = sync all records",
    )
    parser.add_argument(
        "--memory-id",
        action="append",
        default=[],
        help="Specific memory ID to sync. Repeatable.",
    )
    parser.add_argument(
        "--memory-ids",
        type=str,
        default="",
        help="Comma-separated memory IDs to sync.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview records without upload and without updating state.",
    )
    parser.add_argument(
        "--exclude-preference",
        action="store_true",
        help="Exclude preference memories when fetching by cube.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    memory_ids = _parse_memory_ids(args)
    run_once(
        mode=args.mode,
        dry_run=args.dry_run,
        memory_ids=memory_ids,
        include_preference=not args.exclude_preference,
    )


if __name__ == "__main__":
    main()
