#!/usr/bin/env python3
"""
Sync conversations from Codex / Claude / OpenClaw into a knowledge base.

Usage:
  python scripts/sync_conversations_to_kb.py --once
  python scripts/sync_conversations_to_kb.py --daily-at 02:30
  python scripts/sync_conversations_to_kb.py --once --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


logger = logging.getLogger("conversation-sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
load_dotenv()

_DEFAULT_ALLOWED_ROLES = {"user", "assistant"}

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}")
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*([^\s,;]{4,})"
)
_SESSION_ABORT_MARKERS = (
    "<turn_aborted>",
    "the user interrupted the previous turn",
    "interrupted the previous turn on purpose",
    "conversation interrupted",
)
_SESSION_SHORT_GREETINGS = {
    "hi",
    "hello",
    "hey",
    "你好",
    "您好",
    "哈喽",
    "在吗",
    "在么",
    "?",
    "？",
}


@dataclass
class SourceConfig:
    name: str
    path: str
    kind: str = "generic"


@dataclass
class ConversationMessage:
    source: str
    conversation_id: str
    role: str
    content: str
    timestamp: str
    project_path: str = ""
    source_path: str = ""


@dataclass
class SessionExport:
    file_path: Path
    records: list[ConversationMessage]
    hashes: list[str]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int env %s=%s, fallback=%s", name, raw, default)
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items or default


def _expand_path(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def _safe_relpath(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _parse_timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return datetime.now(timezone.utc).isoformat()
        if raw.isdigit():
            return _parse_timestamp(int(raw))
        raw = raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat()
        except ValueError:
            return datetime.now(timezone.utc).isoformat()

    if isinstance(value, (int, float)):
        ts = float(value)
        # milliseconds timestamp
        if ts > 1_000_000_000_000:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return datetime.now(timezone.utc).isoformat()

    return datetime.now(timezone.utc).isoformat()


def _iter_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skip invalid JSONL line in %s:%s", path, lineno)
                continue
            if isinstance(payload, dict):
                records.append(payload)
    return records


def _read_json_or_jsonl(path: Path) -> Any:
    if not path.exists():
        logger.warning("Source file not found: %s", path)
        return []

    if path.suffix.lower() == ".jsonl":
        return _iter_jsonl_dicts(path)

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _collect_text_chunks(value: Any, out: list[str]) -> None:
    if value is None:
        return

    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
        return

    if isinstance(value, list):
        for item in value:
            _collect_text_chunks(item, out)
        return

    if not isinstance(value, dict):
        return

    item_type = str(value.get("type", "")).strip().lower()
    if item_type in {
        "thinking",
        "reasoning",
        "toolcall",
        "tool_call",
        "toolresult",
        "tool_result",
        "function_call",
        "function_call_output",
    }:
        return

    if item_type in {
        "text",
        "input_text",
        "output_text",
        "ai-markdown",
        "markdown",
        "message",
    }:
        text_value = value.get("text")
        if isinstance(text_value, str) and text_value.strip():
            out.append(text_value.strip())

    preferred_keys = (
        "display",
        "text",
        "content",
        "message",
        "query",
        "question",
        "answer",
        "response",
        "output",
        "input",
    )
    handled = False
    for key in preferred_keys:
        if key in value:
            handled = True
            _collect_text_chunks(value.get(key), out)

    if not handled:
        for key, nested in value.items():
            if key == "type":
                continue
            _collect_text_chunks(nested, out)


def _extract_text(value: Any) -> str:
    chunks: list[str] = []
    _collect_text_chunks(value, chunks)
    if not chunks:
        return ""

    deduped: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk in seen:
            continue
        seen.add(chunk)
        deduped.append(chunk)
    return "\n".join(deduped).strip()


def _normalize_role(raw_role: Any) -> str:
    role = str(raw_role or "").strip().lower()
    if role in {"assistant", "model", "bot"}:
        return "assistant"
    if role in {"user", "human", "external", "input"}:
        return "user"
    if role == "toolresult":
        return "tool"
    return role


def _is_noise_message(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return True

    if _env_bool("CONVERSATION_SYNC_FILTER_HARNESS_MESSAGES", True):
        harness_markers = (
            "# agents.md instructions for",
            "<environment_context>",
            "<permissions instructions>",
            "<collaboration_mode>",
            "superpowers bootstrap",
        )
        if any(marker in normalized for marker in harness_markers):
            return True

    if _env_bool("CONVERSATION_SYNC_SKIP_SLASH_COMMANDS", True):
        single_line = "\n" not in normalized
        if single_line and normalized.startswith("/"):
            return True

    # Filter OpenClaw-specific noise patterns
    if _env_bool("CONVERSATION_SYNC_FILTER_OPENCLAW_NOISE", True):
        openclaw_noise_patterns = (
            "只回复ok",
            "只回复 ok",
            "say hi briefly",
            "a new session was started via /new or /reset",
        )
        if any(pattern in normalized for pattern in openclaw_noise_patterns):
            return True

    return False


def _normalize_short_text(text: str) -> str:
    normalized = text.strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip("`'\"")
    normalized = re.sub(r"[。！!？?，,、~～.]+$", "", normalized)
    return normalized.strip()


def _is_aborted_message(text: str) -> bool:
    normalized = _normalize_short_text(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in _SESSION_ABORT_MARKERS)


def _is_short_greeting_message(text: str) -> bool:
    raw = text.strip()
    if raw in _SESSION_SHORT_GREETINGS:
        return True
    normalized = _normalize_short_text(raw)
    if not normalized:
        return False
    return normalized in _SESSION_SHORT_GREETINGS


def _has_substantive_assistant_reply(records: list[ConversationMessage]) -> bool:
    for record in records:
        if record.role != "assistant":
            continue
        content = record.content.strip()
        if not content:
            continue
        if _is_noise_message(content):
            continue
        if _is_aborted_message(content):
            continue
        return True
    return False


def _filter_low_value_sessions(
    items: list[tuple[ConversationMessage, str]]
) -> tuple[list[tuple[ConversationMessage, str]], list[str], dict[str, int]]:
    if not items:
        return [], [], {}
    if not _env_bool("CONVERSATION_SYNC_FILTER_INVALID_SESSIONS", True):
        return items, [], {}

    grouped: dict[tuple[str, str], list[tuple[ConversationMessage, str]]] = {}
    for record, fp in items:
        key = (record.source, record.conversation_id or "unknown")
        grouped.setdefault(key, []).append((record, fp))

    skip_no_assistant = _env_bool("CONVERSATION_SYNC_FILTER_NO_ASSISTANT_SESSIONS", True)
    skip_aborted_short = _env_bool("CONVERSATION_SYNC_FILTER_ABORTED_SHORT_SESSIONS", True)
    skip_greeting_short = _env_bool("CONVERSATION_SYNC_FILTER_GREETING_SHORT_SESSIONS", True)
    aborted_max = max(1, _env_int("CONVERSATION_SYNC_ABORTED_SHORT_MAX_MESSAGES", 2))
    greeting_max = max(1, _env_int("CONVERSATION_SYNC_GREETING_SHORT_MAX_MESSAGES", 2))

    kept_items: list[tuple[ConversationMessage, str]] = []
    filtered_hashes: list[str] = []
    reason_counts: dict[str, int] = {}

    for grouped_items in grouped.values():
        ordered_items = sorted(grouped_items, key=lambda item: item[0].timestamp)
        records = [record for record, _ in ordered_items]
        hashes = [fp for _, fp in ordered_items]

        reason = ""
        if skip_no_assistant and not _has_substantive_assistant_reply(records):
            reason = "no_assistant_substance"
        elif skip_aborted_short and len(records) <= aborted_max:
            if any(_is_aborted_message(record.content) for record in records):
                reason = "aborted_short_session"
        elif skip_greeting_short and len(records) <= greeting_max:
            if all(_is_short_greeting_message(record.content) for record in records):
                reason = "greeting_only_session"

        if reason:
            filtered_hashes.extend(hashes)
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            continue

        kept_items.extend(ordered_items)

    kept_items.sort(key=lambda item: item[0].timestamp)
    if filtered_hashes:
        reason_summary = ", ".join(
            f"{reason}={count}" for reason, count in sorted(reason_counts.items())
        )
        logger.info(
            "Session-level filter skipped sessions=%s records=%s (%s)",
            sum(reason_counts.values()),
            len(filtered_hashes),
            reason_summary,
        )

    return kept_items, filtered_hashes, reason_counts


def _mask_sensitive(text: str) -> str:
    if not _env_bool("CONVERSATION_SYNC_MASK_SENSITIVE", True):
        return text

    masked = text
    masked = _EMAIL_RE.sub("[EMAIL]", masked)
    masked = _PHONE_RE.sub("[PHONE]", masked)
    masked = _BEARER_RE.sub("Bearer [REDACTED]", masked)
    masked = _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", masked)
    return masked


def _clean_text(text: str) -> str:
    cleaned = text.replace("\x00", "").replace("\r\n", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return ""

    max_chars = _env_int("CONVERSATION_SYNC_MAX_CONTENT_CHARS", 6000)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip() + "\n\n[TRUNCATED]"
    return _mask_sensitive(cleaned)


def _conversation_id_from_file(path: Path) -> str:
    stem = path.stem
    if stem:
        return stem
    return "unknown"


def _allowed_roles() -> set[str]:
    values = _env_list("CONVERSATION_SYNC_ALLOWED_ROLES", ["user", "assistant"])
    normalized = {_normalize_role(v) for v in values}
    return {v for v in normalized if v}


def _build_message(
    *,
    source: str,
    source_path: Path,
    conversation_id: str,
    role_raw: Any,
    content_raw: Any,
    timestamp_raw: Any,
    project_path: str = "",
) -> ConversationMessage | None:
    role = _normalize_role(role_raw)
    if role not in _allowed_roles():
        return None

    content = _extract_text(content_raw)
    content = _clean_text(content)
    if not content:
        return None

    if _is_noise_message(content):
        return None

    conv_id = str(conversation_id or "").strip() or _conversation_id_from_file(source_path)
    timestamp = _parse_timestamp(timestamp_raw)

    return ConversationMessage(
        source=source,
        conversation_id=conv_id,
        role=role,
        content=content,
        timestamp=timestamp,
        project_path=project_path.strip(),
        source_path=str(source_path),
    )


def _collect_generic_messages(source: SourceConfig) -> list[ConversationMessage]:
    source_path = _expand_path(source.path)
    payload = _read_json_or_jsonl(source_path)

    items: list[dict[str, Any]] = []
    if isinstance(payload, list):
        items = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        for key in ("conversations", "items", "data", "messages"):
            value = payload.get(key)
            if isinstance(value, list):
                items = [item for item in value if isinstance(item, dict)]
                break
        if not items:
            items = [payload]

    output: list[ConversationMessage] = []
    for item in items:
        conversation_id = str(
            item.get("conversation_id")
            or item.get("conversationId")
            or item.get("session_id")
            or item.get("sessionId")
            or item.get("chat_id")
            or item.get("id")
            or _conversation_id_from_file(source_path)
        )
        project_path = str(item.get("project") or item.get("cwd") or "")

        if isinstance(item.get("messages"), list):
            for msg in item["messages"]:
                if not isinstance(msg, dict):
                    continue
                built = _build_message(
                    source=source.name,
                    source_path=source_path,
                    conversation_id=conversation_id,
                    role_raw=msg.get("role") or msg.get("type"),
                    content_raw=msg,
                    timestamp_raw=msg.get("timestamp") or msg.get("created_at") or item.get("timestamp"),
                    project_path=project_path,
                )
                if built:
                    output.append(built)
            continue

        built = _build_message(
            source=source.name,
            source_path=source_path,
            conversation_id=conversation_id,
            role_raw=item.get("role") or item.get("type") or "user",
            content_raw=item,
            timestamp_raw=item.get("timestamp") or item.get("created_at"),
            project_path=project_path,
        )
        if built:
            output.append(built)

    return output


def _collect_codex_history_messages(source: SourceConfig) -> list[ConversationMessage]:
    source_path = _expand_path(source.path)
    records = _iter_jsonl_dicts(source_path)
    output: list[ConversationMessage] = []

    for item in records:
        built = _build_message(
            source="codex",
            source_path=source_path,
            conversation_id=str(item.get("session_id") or _conversation_id_from_file(source_path)),
            role_raw="user",
            content_raw=item.get("text"),
            timestamp_raw=item.get("ts"),
            project_path="",
        )
        if built:
            output.append(built)

    return output


def _collect_claude_history_messages(source: SourceConfig) -> list[ConversationMessage]:
    source_path = _expand_path(source.path)
    records = _iter_jsonl_dicts(source_path)
    output: list[ConversationMessage] = []

    for item in records:
        built = _build_message(
            source="claude",
            source_path=source_path,
            conversation_id=str(item.get("sessionId") or _conversation_id_from_file(source_path)),
            role_raw="user",
            content_raw=item.get("display"),
            timestamp_raw=item.get("timestamp"),
            project_path=str(item.get("project") or ""),
        )
        if built:
            output.append(built)

    return output


def _collect_codex_session_messages(source: SourceConfig) -> list[ConversationMessage]:
    source_path = _expand_path(source.path)
    records = _iter_jsonl_dicts(source_path)

    session_id = _conversation_id_from_file(source_path)
    cwd = ""
    output: list[ConversationMessage] = []

    for item in records:
        item_type = str(item.get("type") or "")
        if item_type == "session_meta":
            payload = item.get("payload")
            if isinstance(payload, dict):
                session_id = str(payload.get("id") or session_id)
                cwd = str(payload.get("cwd") or cwd)
            continue

        if item_type != "response_item":
            continue

        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type") or "") != "message":
            continue

        built = _build_message(
            source="codex",
            source_path=source_path,
            conversation_id=session_id,
            role_raw=payload.get("role"),
            content_raw=payload.get("content"),
            timestamp_raw=item.get("timestamp"),
            project_path=cwd,
        )
        if built:
            output.append(built)

    return output


def _collect_claude_session_messages(source: SourceConfig) -> list[ConversationMessage]:
    source_path = _expand_path(source.path)
    records = _iter_jsonl_dicts(source_path)

    session_id = _conversation_id_from_file(source_path)
    cwd = ""
    output: list[ConversationMessage] = []

    for item in records:
        session_id = str(item.get("sessionId") or session_id)
        cwd = str(item.get("cwd") or cwd)

        role_raw = item.get("type")
        message_obj = item.get("message") if isinstance(item.get("message"), dict) else {}
        if isinstance(message_obj, dict) and not role_raw:
            role_raw = message_obj.get("role")

        content_raw: Any = None
        if isinstance(message_obj, dict) and "content" in message_obj:
            content_raw = message_obj.get("content")
        elif "content" in item:
            content_raw = item.get("content")

        built = _build_message(
            source="claude",
            source_path=source_path,
            conversation_id=session_id,
            role_raw=role_raw,
            content_raw=content_raw,
            timestamp_raw=item.get("timestamp"),
            project_path=cwd,
        )
        if built:
            output.append(built)

    return output


def _collect_openclaw_session_messages(source: SourceConfig) -> list[ConversationMessage]:
    source_path = _expand_path(source.path)
    records = _iter_jsonl_dicts(source_path)

    session_id = _conversation_id_from_file(source_path)
    cwd = ""
    output: list[ConversationMessage] = []

    for item in records:
        item_type = str(item.get("type") or "")

        if item_type == "session":
            session_id = str(item.get("id") or session_id)
            cwd = str(item.get("cwd") or cwd)
            continue

        # Filter out OpenClaw meta events
        if item_type in {"model_change", "thinking_level_change", "custom"}:
            continue

        if item_type != "message":
            continue

        message_obj = item.get("message")
        if not isinstance(message_obj, dict):
            continue

        # Filter out empty messages
        content = message_obj.get("content")
        if not content or (isinstance(content, list) and len(content) == 0):
            continue

        built = _build_message(
            source="openclaw",
            source_path=source_path,
            conversation_id=session_id,
            role_raw=message_obj.get("role"),
            content_raw=content,
            timestamp_raw=item.get("timestamp") or message_obj.get("timestamp"),
            project_path=cwd,
        )
        if built:
            output.append(built)

    return output


def _collect_messages(source: SourceConfig) -> list[ConversationMessage]:
    if source.kind == "codex_history":
        return _collect_codex_history_messages(source)
    if source.kind == "claude_history":
        return _collect_claude_history_messages(source)
    if source.kind == "codex_session":
        return _collect_codex_session_messages(source)
    if source.kind == "claude_session":
        return _collect_claude_session_messages(source)
    if source.kind == "openclaw_session":
        return _collect_openclaw_session_messages(source)
    return _collect_generic_messages(source)


def _collect_files(root: Path, pattern: str, max_files: int) -> list[Path]:
    if not root.exists():
        return []

    files = [p for p in root.rglob(pattern) if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if max_files > 0:
        files = files[:max_files]
    return files


def _collect_files_by_patterns(root: Path, patterns: list[str], max_files: int) -> list[Path]:
    if not root.exists():
        return []

    merged: dict[str, Path] = {}
    for pattern in patterns:
        for file_path in root.rglob(pattern):
            if not file_path.is_file():
                continue
            merged[file_path.as_posix()] = file_path

    files = list(merged.values())
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if max_files > 0:
        files = files[:max_files]
    return files


def _expand_source_path(name: str, path_str: str, kind: str, recursive: bool = False) -> list[SourceConfig]:
    path = _expand_path(path_str)
    if not path.exists():
        logger.warning("Configured source not found: %s", path)
        return []

    if path.is_file():
        return [SourceConfig(name=name, path=str(path), kind=kind)]

    pattern = "*.jsonl" if recursive else "*.json*"
    files = _collect_files(path, pattern, _env_int("CONVERSATION_SYNC_MAX_FILES_PER_SOURCE", 200))
    return [SourceConfig(name=name, path=str(file), kind=kind) for file in files]


def _load_manual_sources() -> list[SourceConfig]:
    sources: list[SourceConfig] = []
    defaults = [
        ("codex", os.getenv("CODEX_CONVERSATION_FILE", "").strip()),
        ("claude", os.getenv("CLAUDE_CONVERSATION_FILE", "").strip()),
        ("openclaw", os.getenv("OPENCLAW_CONVERSATION_FILE", "").strip()),
    ]

    for name, path in defaults:
        if not path:
            continue
        sources.extend(_expand_source_path(name=name, path_str=path, kind="generic", recursive=True))

    extra_sources = os.getenv("CONVERSATION_SYNC_SOURCES_JSON", "").strip()
    if extra_sources:
        try:
            parsed = json.loads(extra_sources)
            if isinstance(parsed, list):
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip() or "custom"
                    path = str(item.get("path", "")).strip()
                    kind = str(item.get("kind", "generic")).strip() or "generic"
                    recursive = bool(item.get("recursive", True))
                    if not path:
                        continue
                    sources.extend(
                        _expand_source_path(
                            name=name,
                            path_str=path,
                            kind=kind,
                            recursive=recursive,
                        )
                    )
        except json.JSONDecodeError:
            logger.warning("Invalid CONVERSATION_SYNC_SOURCES_JSON, skipping extra sources.")

    return sources


def _discover_default_sources() -> list[SourceConfig]:
    if not _env_bool("CONVERSATION_SYNC_AUTO_DISCOVER", True):
        return []

    max_files = _env_int("CONVERSATION_SYNC_MAX_FILES_PER_SOURCE", 200)
    include_subagents = _env_bool("CONVERSATION_SYNC_INCLUDE_SUBAGENTS", False)

    home = Path.home()
    discovered: list[SourceConfig] = []

    codex_history = home / ".codex" / "history.jsonl"
    if codex_history.exists():
        discovered.append(SourceConfig(name="codex", path=str(codex_history), kind="codex_history"))

    codex_sessions_root = home / ".codex" / "sessions"
    for file_path in _collect_files(codex_sessions_root, "*.jsonl", max_files):
        discovered.append(SourceConfig(name="codex", path=str(file_path), kind="codex_session"))

    claude_history = home / ".claude" / "history.jsonl"
    if claude_history.exists():
        discovered.append(SourceConfig(name="claude", path=str(claude_history), kind="claude_history"))

    claude_projects_root = home / ".claude" / "projects"
    for file_path in _collect_files(claude_projects_root, "*.jsonl", max_files):
        if not include_subagents and "/subagents/" in str(file_path):
            continue
        discovered.append(SourceConfig(name="claude", path=str(file_path), kind="claude_session"))

    openclaw_agents_root = home / ".openclaw" / "agents"
    openclaw_candidates = _collect_files_by_patterns(
        openclaw_agents_root,
        [
            "*.jsonl",
            "*.jsonl.reset.*",
            "*.jsonl.deleted.*",
        ],
        max_files * 6,
    )

    # Filter out test/smoke agents and smoke sessions in orphan archives
    exclude_patterns = _env_list("CONVERSATION_SYNC_OPENCLAW_EXCLUDE_AGENTS", ["smoke-", "test-"])

    for file_path in openclaw_candidates:
        if "/sessions/" not in str(file_path):
            continue

        # Extract agent directory name (e.g., "smoke-test-123" from ".../.openclaw/agents/smoke-test-123/sessions/...")
        try:
            parts = file_path.parts
            agents_idx = parts.index("agents")
            if agents_idx + 1 < len(parts):
                agent_name = parts[agents_idx + 1]
                # Skip if agent name matches any exclude pattern
                if any(agent_name.startswith(pattern) for pattern in exclude_patterns):
                    logger.debug("Skipping excluded OpenClaw agent: %s", agent_name)
                    continue
        except (ValueError, IndexError):
            pass

        # Also filter smoke-* session files in orphan archives
        session_filename = file_path.name
        if any(session_filename.startswith(pattern) for pattern in exclude_patterns):
            logger.debug("Skipping excluded OpenClaw session file: %s", session_filename)
            continue

        discovered.append(SourceConfig(name="openclaw", path=str(file_path), kind="openclaw_session"))

    return discovered


def _load_sources() -> list[SourceConfig]:
    sources = _load_manual_sources() + _discover_default_sources()

    dedup: dict[tuple[str, str], SourceConfig] = {}
    for source in sources:
        key = (source.kind, _expand_path(source.path).as_posix())
        dedup[key] = source

    output = list(dedup.values())
    output.sort(key=lambda s: (s.name, s.kind, s.path))

    if output:
        by_kind: dict[str, int] = {}
        for item in output:
            by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        summary = ", ".join(f"{kind}={count}" for kind, count in sorted(by_kind.items()))
        logger.info("Loaded %s source files (%s)", len(output), summary)

    return output


def _state_path() -> Path:
    return Path(os.getenv("CONVERSATION_SYNC_STATE_PATH", ".memos/conversation_sync_state.json"))


def _load_state() -> set[str]:
    path = _state_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        hashes = data.get("seen_hashes", [])
        if isinstance(hashes, list):
            return set(str(item) for item in hashes)
    except Exception:
        logger.warning("Failed to load state file: %s", path)
    return set()


def _save_state(seen_hashes: set[str], max_hashes: int = 50000) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = list(seen_hashes)
    if len(ordered) > max_hashes:
        ordered = ordered[-max_hashes:]
    payload = {
        "seen_hashes": ordered,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fingerprint(record: ConversationMessage) -> str:
    raw = (
        f"{record.source}|{record.conversation_id}|{record.role}|"
        f"{record.timestamp}|{record.content}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _in_run_dedup_key(record: ConversationMessage) -> str:
    raw = f"{record.source}|{record.conversation_id}|{record.role}|{record.content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sync_sink() -> str:
    return os.getenv("CONVERSATION_SYNC_SINK", "kengine").strip().lower()


def _group_items_by_session(
    items: list[tuple[ConversationMessage, str]]
) -> dict[tuple[str, str], list[tuple[ConversationMessage, str]]]:
    grouped: dict[tuple[str, str], list[tuple[ConversationMessage, str]]] = {}
    for record, fp in items:
        key = (record.source, record.conversation_id or "unknown")
        grouped.setdefault(key, []).append((record, fp))

    for key in grouped:
        grouped[key].sort(key=lambda item: item[0].timestamp)
    return grouped


def _truncate_message_content(content: str) -> str:
    max_chars = _env_int("CONVERSATION_SYNC_MEMOS_MAX_MESSAGE_CHARS", 6000)
    if max_chars <= 0 or len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip() + "\n\n[TRUNCATED]\n"


def _chunk_session_items_for_memos(
    items: list[tuple[ConversationMessage, str]]
) -> list[list[tuple[ConversationMessage, str]]]:
    max_messages = max(1, _env_int("CONVERSATION_SYNC_MEMOS_MAX_MESSAGES_PER_REQUEST", 20))
    max_chars = max(1, _env_int("CONVERSATION_SYNC_MEMOS_MAX_CHARS_PER_REQUEST", 24000))

    chunks: list[list[tuple[ConversationMessage, str]]] = []
    current: list[tuple[ConversationMessage, str]] = []
    current_chars = 0

    for item in items:
        record, _ = item
        estimated_chars = len(_truncate_message_content(record.content))
        should_flush = bool(current) and (
            len(current) >= max_messages or current_chars + estimated_chars > max_chars
        )
        if should_flush:
            chunks.append(current)
            current = []
            current_chars = 0

        current.append(item)
        current_chars += estimated_chars

    if current:
        chunks.append(current)

    return chunks


def _post_to_memos(records: list[ConversationMessage]) -> bool:
    if not records:
        return False

    ordered = sorted(records, key=lambda item: item.timestamp)
    first = ordered[0]
    base_url = os.getenv("MEMOS_SYNC_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    add_path = os.getenv("MEMOS_SYNC_ADD_PATH", "/product/add")
    url = f"{base_url}{add_path}"

    user_id = os.getenv("MEMOS_SYNC_USER_ID", "").strip()
    mem_cube_id = os.getenv("MEMOS_SYNC_MEM_CUBE_ID", "").strip()
    if not user_id:
        raise ValueError("MEMOS_SYNC_USER_ID is required")

    async_mode = os.getenv("CONVERSATION_SYNC_MEMOS_ASYNC_MODE", "sync").strip().lower() or "sync"
    if async_mode not in {"sync", "async"}:
        logger.warning(
            "Invalid CONVERSATION_SYNC_MEMOS_ASYNC_MODE=%s, fallback=sync",
            async_mode,
        )
        async_mode = "sync"

    payload: dict[str, Any] = {
        "user_id": user_id,
        "session_id": first.conversation_id or "conversation_sync",
        "messages": [
            {
                "role": record.role,
                "content": _truncate_message_content(record.content),
                "chat_time": record.timestamp,
            }
            for record in ordered
        ],
        "mode": os.getenv("CONVERSATION_SYNC_MEMOS_ADD_MODE", "fast").strip() or "fast",
        "async_mode": async_mode,
        "info": {
            "source_type": "conversation_sync",
            "conversation_source": first.source,
            "conversation_id": first.conversation_id,
            "message_count": len(ordered),
            "message_roles": [record.role for record in ordered],
            "message_timestamps": [record.timestamp for record in ordered],
            "project_paths": sorted({record.project_path for record in ordered if record.project_path}),
            "source_paths": sorted({record.source_path for record in ordered if record.source_path}),
        },
    }
    if mem_cube_id:
        payload["writable_cube_ids"] = [mem_cube_id]

    headers = {"Content-Type": "application/json"}
    auth_token = os.getenv("MEMOS_SYNC_AUTH_TOKEN", "").strip()
    if auth_token:
        headers["Authorization"] = auth_token

    timeout_seconds = _env_int("MEMOS_SYNC_TIMEOUT_SECONDS", 20)
    response = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
    if response.status_code >= 400:
        logger.error("Add memory failed (%s): %s", response.status_code, response.text)
        return False

    try:
        parsed = response.json()
    except ValueError:
        logger.error("Add memory returned non-JSON body: %s", response.text[:500])
        return False

    if isinstance(parsed, dict):
        code = parsed.get("code")
        if code is not None and str(code) not in {"0", "200"}:
            logger.error("Add memory failed (code=%s): %s", code, parsed)
            return False

        if async_mode == "sync":
            data = parsed.get("data")
            if not isinstance(data, list) or not data:
                logger.error(
                    "Add memory returned empty data in sync mode for conversation %s",
                    first.conversation_id or "unknown",
                )
                return False

    logger.info(
        "Memos import succeeded for conversation %s with %s messages",
        first.conversation_id or "unknown",
        len(ordered),
    )
    return True


def _import_items_to_memos(items: list[tuple[ConversationMessage, str]]) -> set[str]:
    grouped = _group_items_by_session(items)
    success_hashes: set[str] = set()

    for grouped_items in grouped.values():
        for chunk in _chunk_session_items_for_memos(grouped_items):
            records = [record for record, _ in chunk]
            if _post_to_memos(records):
                success_hashes.update(fp for _, fp in chunk)

    return success_hashes


def _kengine_guids() -> tuple[str, str, str]:
    triple = os.getenv("KENGINE_REPO_TRIPLE", "").strip()
    if triple:
        parts = [p.strip() for p in triple.split("/") if p.strip()]
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
            files = {
                "file": (file_path.name, fp, "text/markdown"),
            }
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

    if response is None:
        logger.error("K-Engine import failed: no response for %s", file_path.name)
        return False

    body = response.text or ""
    content_type = (response.headers.get("content-type") or "").lower()

    if response.status_code >= 400:
        logger.error("K-Engine import failed (%s): %s", response.status_code, body)
        return False

    # Some gateways may return a login HTML page with HTTP 200.
    # Treat this as failed import instead of false-positive success.
    if "text/html" in content_type and (
        "<!doctype html" in body.lower() or "登录-潍柴知识管理平台" in body
    ):
        logger.error(
            "K-Engine import failed: received login HTML page (authentication likely missing/expired)."
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
        # Not JSON response; keep compatibility and treat as success
        pass

    logger.info("K-Engine import succeeded for %s", file_path.name)
    return True


def _slug(value: str, max_len: int = 48) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    normalized = normalized.strip("._-") or "unknown"
    return normalized[:max_len]


def _timestamp_to_date(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y%m%d")
    except ValueError:
        return datetime.now(timezone.utc).strftime("%Y%m%d")


def _render_session_markdown(records: list[ConversationMessage]) -> str:
    if not records:
        return "# Empty Conversation\n"

    ordered = sorted(records, key=lambda item: item.timestamp)
    first = ordered[0]
    projects = sorted({r.project_path for r in ordered if r.project_path})
    sources = sorted({r.source_path for r in ordered if r.source_path})

    lines = [
        "# Conversation Session",
        "",
        f"- source: {first.source}",
        f"- conversation_id: {first.conversation_id or 'unknown'}",
        f"- message_count: {len(ordered)}",
        f"- started_at: {ordered[0].timestamp}",
        f"- ended_at: {ordered[-1].timestamp}",
    ]

    if projects:
        lines.append(f"- project_paths: {', '.join(projects)}")
    if sources:
        lines.append(f"- source_files: {', '.join(sources)}")

    lines.append("")
    lines.append("## Conversation")
    lines.append("")

    for msg in ordered:
        lines.append(f"### [{msg.timestamp}] {msg.role}")
        lines.append("")
        lines.append(msg.content)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _write_session_exports(items: list[tuple[ConversationMessage, str]]) -> list[SessionExport]:
    export_dir = Path(os.getenv("CONVERSATION_SYNC_EXPORT_DIR", ".memos/conversation_exports"))
    export_dir.mkdir(parents=True, exist_ok=True)

    grouped = _group_items_by_session(items)

    exports: list[SessionExport] = []
    used_names: set[str] = set()

    for (source, conversation_id), grouped_items in grouped.items():
        records = [record for record, _ in grouped_items]
        hashes = [fp for _, fp in grouped_items]

        date_part = _timestamp_to_date(records[0].timestamp)
        base_name = f"{_slug(source)}_{date_part}_{_slug(conversation_id)}.md"
        file_name = base_name
        suffix = 1
        while file_name in used_names:
            file_name = f"{base_name[:-3]}_{suffix}.md"
            suffix += 1
        used_names.add(file_name)

        file_path = export_dir / file_name
        file_path.write_text(_render_session_markdown(records), encoding="utf-8")
        exports.append(SessionExport(file_path=file_path, records=records, hashes=hashes))

    exports.sort(key=lambda x: x.file_path.name)
    return exports


def _import_items_to_kengine(items: list[tuple[ConversationMessage, str]]) -> set[str]:
    exports = _write_session_exports(items)
    if not exports:
        return set()

    success_hashes: set[str] = set()
    logger.info("Prepared %s markdown files for K-Engine import", len(exports))

    for export in exports:
        if _upload_file_to_kengine(export.file_path):
            success_hashes.update(export.hashes)

    return success_hashes


def _summarize_new_items(items: list[tuple[ConversationMessage, str]]) -> None:
    if not items:
        logger.info("No new conversation records after deduplication")
        return

    by_source: dict[str, int] = {}
    sessions: set[tuple[str, str]] = set()
    for record, _ in items:
        by_source[record.source] = by_source.get(record.source, 0) + 1
        sessions.add((record.source, record.conversation_id))

    source_summary = ", ".join(
        f"{source}={count}" for source, count in sorted(by_source.items())
    )
    logger.info(
        "New records summary: total=%s sessions=%s (%s)",
        len(items),
        len(sessions),
        source_summary,
    )


def run_once(*, dry_run: bool = False) -> None:
    sources = _load_sources()
    if not sources:
        logger.warning("No source configured/discovered for conversation sync.")
        return

    seen = _load_state()

    all_records: list[ConversationMessage] = []
    for source in sources:
        try:
            all_records.extend(_collect_messages(source))
        except Exception as e:
            logger.exception("Failed to parse source %s (%s): %s", source.path, source.kind, e)

    all_records.sort(key=lambda item: item.timestamp)

    max_per_run = _env_int("CONVERSATION_SYNC_MAX_PER_RUN", 2000)
    if len(all_records) > max_per_run:
        all_records = all_records[-max_per_run:]

    if not all_records:
        logger.info("Sync done. success=0 skipped=0 failed=0")
        return

    new_items: list[tuple[ConversationMessage, str]] = []
    in_run_seen: set[str] = set()
    skipped = 0

    for record in all_records:
        fp = _fingerprint(record)
        if fp in seen:
            skipped += 1
            continue

        run_key = _in_run_dedup_key(record)
        if run_key in in_run_seen:
            skipped += 1
            continue
        in_run_seen.add(run_key)

        new_items.append((record, fp))

    if not new_items:
        logger.info("Sync done. success=0 skipped=%s failed=0", skipped)
        return

    new_items, filtered_hashes, _ = _filter_low_value_sessions(new_items)
    skipped += len(filtered_hashes)

    if not dry_run and filtered_hashes:
        for fp in filtered_hashes:
            seen.add(fp)

    if not new_items:
        if not dry_run and filtered_hashes:
            _save_state(seen)
        logger.info("Sync done. success=0 skipped=%s failed=0", skipped)
        return

    _summarize_new_items(new_items)

    if dry_run:
        logger.info("Dry-run mode enabled. No upload executed, state file unchanged.")
        return

    sink = _sync_sink()
    success = 0
    failed = 0

    if sink == "memos":
        success_hashes = _import_items_to_memos(new_items)
        for fp in success_hashes:
            seen.add(fp)
        success = len(success_hashes)
        failed = len(new_items) - success

    elif sink in {"kengine", "kengine_file", "k-engine"}:
        success_hashes = _import_items_to_kengine(new_items)
        for fp in success_hashes:
            seen.add(fp)
        success = len(success_hashes)
        failed = len(new_items) - success

    else:
        raise ValueError("CONVERSATION_SYNC_SINK must be one of: memos, kengine")

    _save_state(seen)
    logger.info("Sync done. success=%s skipped=%s failed=%s", success, skipped, failed)


def _seconds_until(next_run_hhmm: str) -> int:
    hour, minute = next_run_hhmm.split(":")
    now = datetime.now()
    target = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return int((target - now).total_seconds())


def run_daily(daily_at: str, *, dry_run: bool = False) -> None:
    while True:
        sleep_seconds = _seconds_until(daily_at)
        logger.info("Next sync at %s, waiting %s seconds.", daily_at, sleep_seconds)
        time.sleep(sleep_seconds)
        try:
            run_once(dry_run=dry_run)
        except Exception as e:
            logger.exception("Daily sync failed: %s", e)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Codex/Claude/OpenClaw conversations to MemOS or K-Engine"
    )
    parser.add_argument("--once", action="store_true", help="Run sync once and exit")
    parser.add_argument("--daily-at", type=str, help="Run every day at HH:MM (24-hour)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse/clean/summary only, do not upload and do not update sync state",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.once:
        run_once(dry_run=args.dry_run)
        return
    if args.daily_at:
        run_daily(args.daily_at, dry_run=args.dry_run)
        return
    raise SystemExit("Specify --once or --daily-at HH:MM")


if __name__ == "__main__":
    main()
