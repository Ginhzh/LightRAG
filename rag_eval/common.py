from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_MODES = ["naive", "local", "global", "hybrid", "mix"]
SCORE_FIELDS = [
    "relevance_score",
    "factual_grounding_score",
    "relation_score",
    "causal_score",
    "boundary_score",
    "structure_score",
    "completeness_score",
]


@dataclass(frozen=True)
class LightRAGEndpoints:
    answer_url: str
    context_url: str


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def parse_modes(raw_modes: str | list[str] | None) -> list[str]:
    if raw_modes is None:
        return list(DEFAULT_MODES)
    if isinstance(raw_modes, str):
        modes = [item.strip() for item in raw_modes.split(",") if item.strip()]
    else:
        modes = [str(item).strip() for item in raw_modes if str(item).strip()]
    invalid = sorted(set(modes) - set(DEFAULT_MODES))
    if invalid:
        raise ValueError(f"Unsupported modes: {', '.join(invalid)}")
    return modes or list(DEFAULT_MODES)


def ensure_output_dir(path: str | Path) -> Path:
    output_dir = Path(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def read_json(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def iter_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def completed_pairs(path: str | Path) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in iter_jsonl(path):
        question_id = row.get("question_id")
        query_mode = row.get("query_mode")
        if question_id and query_mode:
            pairs.add((str(question_id), str(query_mode)))
    return pairs


def normalize_lightrag_endpoints(endpoint: str) -> LightRAGEndpoints:
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint:
        raise ValueError("endpoint is empty")

    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"endpoint must be an absolute HTTP URL: {endpoint}")

    if endpoint.endswith("/query/data"):
        base = endpoint[: -len("/query/data")]
    elif endpoint.endswith("/query"):
        base = endpoint[: -len("/query")]
    else:
        base = endpoint
    return LightRAGEndpoints(answer_url=f"{base}/query", context_url=f"{base}/query/data")


def build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("LIGHTRAG_API_KEY") or os.getenv("RAG_EVAL_API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key
    extra = os.getenv("RAG_EVAL_HEADERS_JSON", "").strip()
    if extra:
        try:
            parsed = json.loads(extra)
        except json.JSONDecodeError as exc:
            raise ValueError("RAG_EVAL_HEADERS_JSON must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("RAG_EVAL_HEADERS_JSON must be a JSON object")
        headers.update({str(key): str(value) for key, value in parsed.items()})
    return headers


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "question_id",
        "question_type",
        "query_mode",
        "latency_ms",
        "error_message",
        "total_score",
        *SCORE_FIELDS,
        "flags",
        "question",
        "answer",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if isinstance(out.get("flags"), list):
                out["flags"] = ",".join(out["flags"])
            writer.writerow(out)


def load_yaml_like(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None
    if yaml is not None:
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return loaded if isinstance(loaded, dict) else {}

    # Minimal fallback for simple config files: key: scalar/list.
    config: dict[str, Any] = {}
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip("'\"")
        if value.startswith("[") and value.endswith("]"):
            config[key.strip()] = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
        elif value.lower() in {"true", "false"}:
            config[key.strip()] = value.lower() == "true"
        else:
            try:
                config[key.strip()] = int(value)
            except ValueError:
                try:
                    config[key.strip()] = float(value)
                except ValueError:
                    config[key.strip()] = value
    return config


def load_dotenv_file(path: str | Path = ".env") -> None:
    target = Path(path)
    if not target.exists():
        return
    for raw_line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or any(char.isspace() for char in key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def env_summary() -> dict[str, str]:
    keys = [
        "LLM_BINDING",
        "LLM_MODEL",
        "LLM_BINDING_HOST",
        "EMBEDDING_BINDING",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
        "WORKING_DIR",
        "INPUT_DIR",
        "LIGHTRAG_GRAPH_STORAGE",
        "LIGHTRAG_VECTOR_STORAGE",
        "RERANK_BINDING",
    ]
    return {key: os.getenv(key, "") for key in keys if os.getenv(key, "")}
