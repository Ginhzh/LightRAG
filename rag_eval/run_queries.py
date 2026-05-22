from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rag_eval.common import (
    append_jsonl,
    build_headers,
    completed_pairs,
    ensure_output_dir,
    load_yaml_like,
    load_dotenv_file,
    normalize_lightrag_endpoints,
    parse_modes,
    read_json,
    utc_now_iso,
    write_csv,
)
from rag_eval.generate_questions import generate_questions


LOGGER = logging.getLogger("rag_eval.run_queries")


def post_json(url: str, payload: dict[str, Any], *, timeout: float, headers: dict[str, str]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {error_body[:1000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc
    if not data.strip():
        return {}
    parsed = json.loads(data)
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def extract_answer(raw_response: dict[str, Any]) -> str:
    for key in ("response", "answer", "content"):
        value = raw_response.get(key)
        if isinstance(value, str):
            return value
    llm_response = raw_response.get("llm_response")
    if isinstance(llm_response, dict) and isinstance(llm_response.get("content"), str):
        return llm_response["content"]
    return ""


def extract_retrieved_context(
    raw_response: dict[str, Any] | None,
    data_response: dict[str, Any] | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if raw_response and isinstance(raw_response.get("references"), list):
        context["references"] = raw_response["references"]
    if data_response:
        for key in ("status", "message", "data", "metadata"):
            if key in data_response:
                context[key] = data_response[key]
    return context


def run_one(
    question: dict[str, Any],
    mode: str,
    *,
    answer_url: str,
    context_url: str,
    timeout: float,
    headers: dict[str, str],
    top_k: int | None,
    chunk_top_k: int | None,
    include_context: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": question["question"],
        "mode": mode,
        "include_references": True,
        "include_chunk_content": True,
        "stream": False,
    }
    if top_k:
        payload["top_k"] = top_k
    if chunk_top_k:
        payload["chunk_top_k"] = chunk_top_k

    started = time.perf_counter()
    raw_response: dict[str, Any] | None = None
    data_response: dict[str, Any] | None = None
    error_message = ""
    try:
        raw_response = post_json(answer_url, payload, timeout=timeout, headers=headers)
        if include_context:
            data_payload = {key: value for key, value in payload.items() if key not in {"include_chunk_content", "include_references"}}
            data_response = post_json(context_url, data_payload, timeout=timeout, headers=headers)
    except Exception as exc:
        error_message = str(exc)
        LOGGER.warning("query failed question=%s mode=%s error=%s", question["id"], mode, error_message)

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    answer = extract_answer(raw_response or {})
    return {
        "question_id": question["id"],
        "question": question["question"],
        "question_type": question["type"],
        "expected_strength": question.get("expected_strength", ""),
        "query_mode": mode,
        "answer": answer,
        "latency_ms": latency_ms,
        "error_message": error_message,
        "raw_response": raw_response or {},
        "retrieved_context": extract_retrieved_context(raw_response, data_response),
        "created_at": utc_now_iso(),
    }


def _load_or_generate_questions(output_dir: Path, num_questions: int) -> list[dict[str, Any]]:
    path = output_dir / "questions.json"
    questions = read_json(path, default=None)
    if isinstance(questions, list) and questions:
        return questions[:num_questions]
    questions = generate_questions(num_questions=num_questions, document_name="诡秘之主(501-1000章).txt")
    from rag_eval.common import write_json

    write_json(path, questions)
    return questions


def run_queries(args: argparse.Namespace) -> list[dict[str, Any]]:
    output_dir = ensure_output_dir(args.output_dir)
    questions = _load_or_generate_questions(output_dir, args.num_questions)
    if args.limit:
        questions = questions[: args.limit]

    modes = parse_modes(args.modes)
    endpoints = normalize_lightrag_endpoints(args.endpoint)
    results_path = output_dir / "results.jsonl"
    done = completed_pairs(results_path) if args.resume else set()
    headers = build_headers()

    tasks = [
        (question, mode)
        for question in questions
        for mode in modes
        if (question["id"], mode) not in done
    ]
    LOGGER.info("scheduled %s query tasks; skipped %s completed pairs", len(tasks), len(done))

    rows: list[dict[str, Any]] = []
    if args.concurrency <= 1:
        for question, mode in tasks:
            row = run_one(
                question,
                mode,
                answer_url=endpoints.answer_url,
                context_url=endpoints.context_url,
                timeout=args.timeout,
                headers=headers,
                top_k=args.top_k,
                chunk_top_k=args.chunk_top_k,
                include_context=not args.no_context,
            )
            append_jsonl(results_path, row)
            rows.append(row)
            if args.sleep > 0:
                time.sleep(args.sleep)
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = []
            for question, mode in tasks:
                futures.append(
                    executor.submit(
                        run_one,
                        question,
                        mode,
                        answer_url=endpoints.answer_url,
                        context_url=endpoints.context_url,
                        timeout=args.timeout,
                        headers=headers,
                        top_k=args.top_k,
                        chunk_top_k=args.chunk_top_k,
                        include_context=not args.no_context,
                    )
                )
                if args.sleep > 0:
                    time.sleep(args.sleep)
            for future in as_completed(futures):
                row = future.result()
                append_jsonl(results_path, row)
                rows.append(row)

    all_rows = [*read_jsonl_as_dicts(results_path)]
    write_csv(output_dir / "results.csv", all_rows)
    return rows


def read_jsonl_as_dicts(path: Path) -> list[dict[str, Any]]:
    from rag_eval.common import iter_jsonl

    return iter_jsonl(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run LightRAG queries across modes.")
    parser.add_argument("--config", default="rag_eval/config.yaml")
    parser.add_argument("--modes", default=None, help="Comma-separated modes, e.g. naive,local,global,hybrid,mix")
    parser.add_argument("--num-questions", type=int, default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--chunk-top-k", type=int, default=None)
    parser.add_argument("--no-context", action="store_true")
    return parser


def apply_config_defaults(args: argparse.Namespace) -> argparse.Namespace:
    load_dotenv_file(".env")
    config = load_yaml_like(args.config)
    defaults = {
        "modes": "naive,local,global,hybrid,mix",
        "num_questions": 30,
        "output_dir": "outputs",
        "endpoint": "http://10.12.222.57:9621",
        "concurrency": 1,
        "sleep": 0.5,
        "timeout": 120.0,
        "top_k": None,
        "chunk_top_k": None,
    }
    for key, value in defaults.items():
        current = getattr(args, key)
        if current is None:
            setattr(args, key, config.get(key, value))
    return args


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = apply_config_defaults(build_parser().parse_args())
    rows = run_queries(args)
    print(f"Wrote {len(rows)} new query results to {Path(args.output_dir) / 'results.jsonl'}")


if __name__ == "__main__":
    main()
