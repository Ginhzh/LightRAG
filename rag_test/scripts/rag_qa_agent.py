#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[2]

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TOP_K = 5
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2
DEFAULT_CONTEXT_CHARS = 12000
DEFAULT_CHUNK_CHARS = 1800
LIGHTRAG_QUERY_MODES = {"local", "global", "hybrid", "naive", "mix", "bypass"}


@dataclass(slots=True)
class RetrievedSource:
    index: int
    title: str
    url: str
    score: float | None
    content: str


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def ensure_env_loaded() -> None:
    env_file = Path(os.getenv("ENV_FILE", ROOT_DIR / ".env"))
    load_env_file(env_file)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _normalize_api_base(api_base: str) -> str:
    api_base = api_base.strip().rstrip("/")
    if api_base.endswith("/v1"):
        return api_base
    return f"{api_base}/v1"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _default_user_id() -> str:
    for key in ("QA_USER_ID", "MEMOS_SYNC_USER_ID", "EXTERNAL_RAG_USER_ID", "USER_ID"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return "demo-user"


def _default_conversation_id() -> str:
    return os.getenv("EXTERNAL_RAG_CONVERSATION_ID", "").strip()


def _load_json_env(name: str, default: Any) -> Any:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _normalize_score(item: dict[str, Any]) -> float | None:
    meta = item.get("metadata", {})
    if not isinstance(meta, dict):
        return None
    for key in ("relativity", "score", "similarity"):
        value = meta.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[TRUNCATED]"


def _build_rag_headers() -> dict[str, str]:
    headers = {"content-type": "application/json"}
    extra = _load_json_env("EXTERNAL_RAG_HEADERS_JSON", {})
    if isinstance(extra, dict):
        headers.update({str(k): str(v) for k, v in extra.items()})
    return headers


def _build_llm_headers() -> dict[str, str]:
    headers = {"content-type": "application/json"}
    return headers


def _is_lightrag_query_data_endpoint(url: str) -> bool:
    provider = os.getenv("EXTERNAL_RAG_PROVIDER", "").strip().lower()
    return provider in {"lightrag", "lightrag_query_data"} or url.rstrip("/").endswith(
        "/query/data"
    )


def _lightrag_mode(prompt_mode: str) -> str:
    configured = os.getenv("LIGHTRAG_QUERY_MODE", "").strip()
    if configured:
        if configured not in LIGHTRAG_QUERY_MODES:
            raise ValueError(
                "LIGHTRAG_QUERY_MODE must be one of: "
                + ", ".join(sorted(LIGHTRAG_QUERY_MODES))
            )
        return configured

    # Default to a fair RAG-vs-GraphRAG comparison when the caller only selects
    # the answer synthesis style.
    return "mix" if prompt_mode == "graph" else "naive"


def _build_lightrag_payload(question: str, prompt_mode: str, top_k: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": question,
        "mode": _lightrag_mode(prompt_mode),
        "top_k": _env_int("LIGHTRAG_QUERY_TOP_K", top_k),
        "chunk_top_k": _env_int("LIGHTRAG_QUERY_CHUNK_TOP_K", top_k),
    }

    enable_rerank = os.getenv("LIGHTRAG_QUERY_ENABLE_RERANK", "").strip()
    if enable_rerank:
        payload["enable_rerank"] = _env_bool("LIGHTRAG_QUERY_ENABLE_RERANK", True)

    return payload


def _build_rag_payload(question: str, user_id: str, conversation_id: str, mode: str) -> dict[str, Any]:
    template = _load_json_env("EXTERNAL_RAG_REQUEST_TEMPLATE_JSON", None)
    if isinstance(template, dict):
        context = {
            "query": question,
            "user_id": user_id,
            "conversation_id": conversation_id,
        }

        def render(value: Any) -> Any:
            if isinstance(value, str):
                rendered = value
                for key, replacement in context.items():
                    rendered = rendered.replace("{" + key + "}", replacement)
                return rendered
            if isinstance(value, list):
                return [render(item) for item in value]
            if isinstance(value, dict):
                return {k: render(v) for k, v in value.items()}
            return value

        return render(template)

    return {
        "id": "1",
        "content": question,
        "conversationId": conversation_id,
        "model": int(os.getenv("EXTERNAL_RAG_MODEL", "1")),
        "label": "",
        "pluginId": "",
        "questionId": "",
        "tag": "",
        "body": {
            "dataSource": _load_json_env("EXTERNAL_RAG_DATA_SOURCE_JSON", ["knowledge"]),
            "language": os.getenv("EXTERNAL_RAG_LANGUAGE", "cn"),
            "mode": mode,
        },
    }


def _extract_lightrag_query_data_items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []

    payload = data.get("data")
    if not isinstance(payload, dict):
        return []

    references_by_id: dict[str, dict[str, Any]] = {}
    for ref in payload.get("references", []):
        if isinstance(ref, dict):
            ref_id = str(ref.get("reference_id") or "")
            if ref_id:
                references_by_id[ref_id] = ref

    items: list[dict[str, Any]] = []
    for chunk in payload.get("chunks", []):
        if not isinstance(chunk, dict):
            continue
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        ref_id = str(chunk.get("reference_id") or "")
        ref = references_by_id.get(ref_id, {})
        file_path = str(chunk.get("file_path") or ref.get("file_path") or "").strip()
        items.append(
            {
                "title": file_path or ref_id or str(chunk.get("chunk_id") or "chunk"),
                "content": content,
                "url": file_path,
                "metadata": {
                    "source": file_path,
                    "chunk_id": chunk.get("chunk_id"),
                    "reference_id": ref_id,
                },
            }
        )

    if items:
        return items

    for relation in payload.get("relationships", []):
        if not isinstance(relation, dict):
            continue
        description = str(relation.get("description") or "").strip()
        if not description:
            continue
        src_id = str(relation.get("src_id") or "").strip()
        tgt_id = str(relation.get("tgt_id") or "").strip()
        title = f"{src_id} -> {tgt_id}".strip(" ->") or "relationship"
        items.append(
            {
                "title": title,
                "content": description,
                "url": str(relation.get("file_path") or ""),
                "metadata": {
                    "source": relation.get("file_path"),
                    "reference_id": relation.get("reference_id"),
                    "weight": relation.get("weight"),
                },
            }
        )

    for entity in payload.get("entities", []):
        if not isinstance(entity, dict):
            continue
        description = str(entity.get("description") or "").strip()
        if not description:
            continue
        items.append(
            {
                "title": str(entity.get("entity_name") or "entity"),
                "content": description,
                "url": str(entity.get("file_path") or ""),
                "metadata": {
                    "source": entity.get("file_path"),
                    "reference_id": entity.get("reference_id"),
                    "entity_type": entity.get("entity_type"),
                },
            }
        )

    return items


def retrieve_sources(
    question: str,
    *,
    top_k: int,
    user_id: str,
    conversation_id: str | None = None,
) -> list[RetrievedSource]:
    ensure_env_loaded()
    url = os.getenv("EXTERNAL_RAG_URL", "").strip()
    if not url:
        raise ValueError("EXTERNAL_RAG_URL is empty")

    prompt_mode = os.getenv("QA_MODE", "rag")
    is_lightrag = _is_lightrag_query_data_endpoint(url)
    if is_lightrag:
        payload = _build_lightrag_payload(question, prompt_mode, top_k)
    else:
        payload = _build_rag_payload(
            question=question,
            user_id=user_id,
            conversation_id=conversation_id or _default_conversation_id(),
            mode=prompt_mode,
        )

    response = requests.post(
        url,
        json=payload,
        headers=_build_rag_headers(),
        timeout=int(os.getenv("EXTERNAL_RAG_TIMEOUT_SECONDS", "30")),
        stream=True,
    )
    try:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if is_lightrag:
            raw_items = _extract_lightrag_query_data_items(response.json())
        elif "text/event-stream" in content_type:
            raw_items = _extract_sse_items(response, top_k)
        else:
            raw_items = _extract_json_items(response.json())
        return _normalize_items(raw_items, top_k=top_k)
    finally:
        response.close()


def _extract_json_items(data: Any) -> list[dict[str, Any]]:
    items_path = os.getenv("EXTERNAL_RAG_ITEMS_PATH", "").strip()
    if items_path:
        target = data
        for part in items_path.split("."):
            if isinstance(target, dict) and part in target:
                target = target[part]
            elif isinstance(target, list) and part.isdigit():
                idx = int(part)
                if 0 <= idx < len(target):
                    target = target[idx]
                else:
                    return []
            else:
                return []
        if isinstance(target, list):
            return [item for item in target if isinstance(item, dict)]
        if isinstance(target, dict):
            return [target]
        return []

    candidates: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if any(k in node for k in ("content", "text", "snippet", "answer", "memory", "passage")):
                candidates.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return candidates


def _extract_sse_items(response: requests.Response, top_k: int) -> list[dict[str, Any]]:
    raw_items: list[dict[str, Any]] = []
    markdown_chunks: list[str] = []
    data_lines: list[str] = []
    event_count = 0

    def flush() -> bool:
        nonlocal data_lines, event_count
        if not data_lines:
            return False
        data_str = "\n".join(data_lines).strip()
        data_lines = []
        event_count += 1
        if not data_str or data_str == "[DONE]":
            return False
        try:
            payload = json.loads(data_str)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False

        messages = payload.get("message")
        if not isinstance(messages, list):
            return False

        has_source = False
        for item in messages:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            contents = item.get("contents", {})
            if item_type == "source":
                source_items = []
                if isinstance(contents, dict):
                    source_items = contents.get("source", [])
                if isinstance(source_items, list):
                    for source_item in source_items:
                        if isinstance(source_item, dict):
                            raw_items.append(
                                {
                                    "id": source_item.get("nid") or source_item.get("id"),
                                    "title": source_item.get("title", ""),
                                    "content": source_item.get("content", ""),
                                    "url": source_item.get("url") or source_item.get("mobileUrl", ""),
                                    "source_type": "knowledge",
                                }
                            )
                            has_source = True
            elif item_type == "ai-markdown":
                text = ""
                if isinstance(contents, dict):
                    text = contents.get("text", "")
                if isinstance(text, str) and text:
                    markdown_chunks.append(text)

        if has_source and len(raw_items) >= top_k:
            return True
        if event_count >= int(os.getenv("EXTERNAL_RAG_SSE_MAX_EVENTS", "500")):
            return True
        return False

    for line in response.iter_lines(decode_unicode=True):
        if line is None:
            continue
        line = line.strip("\r")
        if line == "":
            if flush():
                break
            continue
        if line.startswith("event:"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())

    flush()

    if raw_items:
        return raw_items
    answer_text = "".join(markdown_chunks).strip()
    if answer_text:
        return [{"id": "answer", "content": answer_text, "source_type": "answer"}]
    return []


def _normalize_items(raw_items: list[dict[str, Any]], top_k: int) -> list[RetrievedSource]:
    seen: set[str] = set()
    sources: list[RetrievedSource] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("text") or item.get("snippet") or "").strip()
        if not content or content in seen:
            continue
        seen.add(content)

        meta = item.get("metadata", {})
        if not isinstance(meta, dict):
            meta = {}
        raw_sources = meta.get("sources")
        source_meta: dict[str, Any] = {}
        if isinstance(raw_sources, list) and raw_sources:
            first = raw_sources[0]
            if isinstance(first, dict):
                source_meta = first

        title = str(item.get("title") or source_meta.get("title") or meta.get("source") or f"source-{index}").strip()
        url = str(item.get("url") or source_meta.get("url") or "").strip()
        score = _normalize_score(item)
        sources.append(
            RetrievedSource(
                index=index,
                title=title or f"source-{index}",
                url=url,
                score=score,
                content=_truncate(content, _env_int("QA_CONTEXT_CHUNK_CHARS", DEFAULT_CHUNK_CHARS)),
            )
        )
        if len(sources) >= top_k:
            break
    return sources


def build_context_block(sources: list[RetrievedSource]) -> str:
    lines: list[str] = ["检索上下文如下，仅可据此回答：", ""]
    for item in sources:
        lines.append(f"[{item.index}] {item.title}")
        if item.url:
            lines.append(f"url: {item.url}")
        if item.score is not None:
            lines.append(f"score: {item.score:.4f}")
        lines.append("content:")
        lines.append(item.content)
        lines.append("")

    context = "\n".join(lines).strip()
    return _truncate(context, _env_int("QA_MAX_CONTEXT_CHARS", DEFAULT_CONTEXT_CHARS))


def build_messages(question: str, context_block: str, mode: str) -> list[dict[str, str]]:
    system_prompt = (
        "你是企业知识库问答助手。"
        "你只能依据给定的检索上下文回答，不要编造。"
        "如果上下文不足，直接说明缺少什么信息。"
        "回答要求简洁、准确，并尽量引用使用到的编号。"
    )
    if mode == "graph":
        system_prompt += (
            "当前模式偏向 Graph-RAG。"
            "如果上下文里出现系统、接口、表、缓存、消息、依赖、因果、流程等关系，请优先用多跳关系组织答案。"
        )
    else:
        system_prompt += "当前模式偏向普通 RAG。优先回答直接事实。"

    user_prompt = (
        f"问题：{question}\n\n"
        f"{context_block}\n\n"
        "请直接给出中文答案。"
        "如果能确定结论，请在末尾附上你使用到的引用编号，例如 [1][3]。"
        "如果不能确定，请明确说“根据当前上下文无法确认”。"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_llm_payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    ensure_env_loaded()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY or DEEPSEEK_API_KEY is required")

    api_base = (
        os.getenv("DEEPSEEK_API_BASE", "").strip()
        or os.getenv("OPENAI_API_BASE", "").strip()
        or "https://api.deepseek.com"
    )

    return {
        "api_key": api_key,
        "api_base": _normalize_api_base(api_base),
        "model": os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "temperature": _env_float("QA_TEMPERATURE", DEFAULT_TEMPERATURE),
        "max_tokens": _env_int("QA_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        "messages": messages,
    }


def generate_answer(messages: list[dict[str, str]]) -> str:
    payload = build_llm_payload(messages)
    url = payload["api_base"].rstrip("/") + "/chat/completions"
    response = requests.post(
        url,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {payload['api_key']}",
        },
        json={
            "model": payload["model"],
            "messages": payload["messages"],
            "temperature": payload["temperature"],
            "max_tokens": payload["max_tokens"],
        },
        timeout=_env_int("QA_LLM_TIMEOUT_SECONDS", 60),
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def answer_question(
    question: str,
    *,
    top_k: int,
    mode: str,
    user_id: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    ensure_env_loaded()
    sources = retrieve_sources(
        question,
        top_k=top_k,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if not sources:
        return {
            "question": question,
            "answer": "根据当前上下文无法确认。",
            "sources": [],
            "context": "",
        }

    context_block = build_context_block(sources)
    messages = build_messages(question, context_block, mode)
    answer = generate_answer(messages)

    return {
        "question": question,
        "answer": answer,
        "sources": [
            {
                "index": item.index,
                "title": item.title,
                "url": item.url,
                "score": item.score,
            }
            for item in sources
        ],
        "context": context_block,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple RAG / Graph-RAG QA agent")
    parser.add_argument("question", nargs="?", help="Question to ask")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of retrieved chunks")
    parser.add_argument(
        "--mode",
        choices=("rag", "graph"),
        default=os.getenv("QA_MODE", "rag"),
        help="Prompt mode used for answer synthesis",
    )
    parser.add_argument("--user-id", default=None, help="Override user id for retrieval")
    parser.add_argument(
        "--conversation-id",
        default=None,
        help="Override conversation id used by the retrieval service",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument(
        "--show-context",
        action="store_true",
        help="Print retrieved context before the answer",
    )
    return parser.parse_args()


def main() -> int:
    ensure_env_loaded()
    args = parse_args()

    question = args.question or ""
    if not question:
        if sys.stdin.isatty():
            question = input("Question: ").strip()
        else:
            question = sys.stdin.read().strip()

    if not question:
        raise SystemExit("question is required")

    result = answer_question(
        question,
        top_k=args.top_k,
        mode=args.mode,
        user_id=args.user_id or _default_user_id(),
        conversation_id=args.conversation_id or _default_conversation_id(),
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.show_context and result.get("context"):
        print("=== CONTEXT ===")
        print(result["context"])
        print()

    print("=== ANSWER ===")
    print(result["answer"])
    print()
    if result.get("sources"):
        print("=== SOURCES ===")
        for item in result["sources"]:
            suffix = f" ({item['url']})" if item.get("url") else ""
            score = f" score={item['score']:.4f}" if item.get("score") is not None else ""
            print(f"[{item['index']}] {item['title']}{score}{suffix}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
