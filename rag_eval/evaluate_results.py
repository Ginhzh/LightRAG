from __future__ import annotations

import argparse
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from rag_eval.common import SCORE_FIELDS, ensure_output_dir, iter_jsonl, load_dotenv_file, read_json, write_csv


LOGGER = logging.getLogger("rag_eval.evaluate_results")
RELATION_WORDS = ("关系", "关联", "影响", "连接", "来源", "对象", "用途", "人物", "组织", "地点", "物品")
CAUSAL_WORDS = ("因为", "所以", "导致", "为了", "目的", "动机", "结果", "先", "后", "最终", "因果")
BOUNDARY_LEAK_WORDS = ("后续章节", "后文", "后来", "最终", "已经在后面", "真实身份", "结局")
STRUCTURE_WORDS = ("目标", "人物", "资源", "风险", "行动", "短期", "长期", "已发生", "计划", "可能")


def _clamp(value: int) -> int:
    return max(0, min(5, value))


def _context_counts(context: dict[str, Any]) -> tuple[int, int, int]:
    data = context.get("data") if isinstance(context, dict) else {}
    if not isinstance(data, dict):
        return 0, 0, 0
    return (
        len(data.get("entities", []) if isinstance(data.get("entities"), list) else []),
        len(data.get("relationships", []) if isinstance(data.get("relationships"), list) else []),
        len(data.get("chunks", []) if isinstance(data.get("chunks"), list) else []),
    )


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def rule_score(question: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    if record.get("error_message"):
        return {
            **{field: 0 for field in SCORE_FIELDS},
            "total_score": 0,
            "flags": ["mode_error"],
            "short_reason": f"模式调用失败：{record.get('error_message')}",
            "better_answer_outline": [],
        }

    answer = str(record.get("answer") or "").strip()
    question_text = str(question.get("question") or record.get("question") or "")
    question_type = str(question.get("type") or record.get("question_type") or "")
    context = record.get("retrieved_context") if isinstance(record.get("retrieved_context"), dict) else {}
    entities_count, relationships_count, chunks_count = _context_counts(context)
    flags: list[str] = []

    answer_len = len(answer)
    relevance = 1 if answer else 0
    if answer_len >= 80:
        relevance += 2
    if any(token in answer for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9·]{2,}", question_text)[:8]):
        relevance += 2

    factual = 2 if answer else 0
    if chunks_count or entities_count or relationships_count or context.get("references"):
        factual += 2
    if "无法" in answer or "不能确定" in answer:
        factual += 1

    relation = 1 if answer else 0
    if _contains_any(answer, RELATION_WORDS):
        relation += 2
    if entities_count or relationships_count:
        relation += 1
    if question_type in {"local_relation", "global_relation"} and "—" in answer:
        relation += 1

    causal = 1 if answer else 0
    if _contains_any(answer, CAUSAL_WORDS):
        causal += 2
    if question_type == "causal_chain" and ("先" in answer or "后" in answer):
        causal += 1
    if "目的" in answer or "动机" in answer:
        causal += 1

    boundary = 5 if answer else 0
    boundary_constraint = str(question.get("boundary_constraint") or "")
    if boundary_constraint and _contains_any(answer, BOUNDARY_LEAK_WORDS):
        boundary -= 2
        flags.append("possible_timeline_leak")
    if answer_len > 1800:
        boundary -= 1
        flags.append("too_broad")
    if chunks_count > 25 or relationships_count > 40:
        flags.append("over_retrieval")

    structure = 1 if answer else 0
    if "\n" in answer or "：" in answer or ":" in answer or "1." in answer:
        structure += 2
    if _contains_any(answer, STRUCTURE_WORDS):
        structure += 2

    completeness = 1 if answer else 0
    expected = question.get("ideal_answer_criteria", [])
    if isinstance(expected, list) and expected:
        matched = sum(1 for criterion in expected if any(token in answer for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9·]{2,}", str(criterion))[:4]))
        completeness += min(4, matched + (1 if answer_len > 160 else 0))
    elif answer_len > 200:
        completeness += 3

    if answer_len < 80:
        flags.append("too_shallow")
    if not (chunks_count or entities_count or relationships_count or context.get("references")):
        flags.append("missing_evidence")
    if answer and ("张冠李戴" in answer or "不一致" in answer):
        flags.append("entity_confusion")
    if answer and chunks_count == 0 and relationships_count == 0 and entities_count == 0:
        flags.append("under_retrieval")

    scores = {
        "relevance_score": _clamp(relevance),
        "factual_grounding_score": _clamp(factual),
        "relation_score": _clamp(relation),
        "causal_score": _clamp(causal),
        "boundary_score": _clamp(boundary),
        "structure_score": _clamp(structure),
        "completeness_score": _clamp(completeness),
    }
    return {
        **scores,
        "total_score": sum(scores.values()),
        "flags": sorted(set(flags)),
        "short_reason": "规则评分：基于答案长度、结构、关系/因果词、上下文返回量和边界约束初筛。",
        "better_answer_outline": question.get("ideal_answer_criteria", []),
    }


JUDGE_PROMPT = """你是 RAG 评测裁判。请根据问题、查询模式、答案、检索上下文，对答案进行评分。
重点判断：
1. 是否忠于上下文；
2. 是否回答了问题；
3. 是否正确处理人物、组织、地点、物品关系；
4. 是否出现时间线泄漏；
5. 是否混入后续剧情；
6. 是否只是语义相似内容拼盘；
7. 是否体现该查询模式应有优势。

请输出严格 JSON：
{
  "relevance_score": 0-5,
  "factual_grounding_score": 0-5,
  "relation_score": 0-5,
  "causal_score": 0-5,
  "boundary_score": 0-5,
  "structure_score": 0-5,
  "completeness_score": 0-5,
  "total_score": 0-35,
  "flags": [],
  "short_reason": "...",
  "better_answer_outline": ["...", "..."]
}
"""


def llm_judge(question: dict[str, Any], record: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    endpoint = os.getenv("RAG_EVAL_JUDGE_ENDPOINT") or os.getenv("LLM_BINDING_HOST")
    api_key = os.getenv("RAG_EVAL_JUDGE_API_KEY") or os.getenv("LLM_BINDING_API_KEY")
    model = os.getenv("RAG_EVAL_JUDGE_MODEL") or os.getenv("LLM_MODEL", "deepseek-chat")
    if not endpoint:
        return fallback
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": JUDGE_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "query_mode": record.get("query_mode"),
                        "answer": record.get("answer"),
                        "retrieved_context": record.get("retrieved_context"),
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        request = Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        with urlopen(request, timeout=float(os.getenv("RAG_EVAL_JUDGE_TIMEOUT", "120"))) as response:
            raw = json.loads(response.read().decode("utf-8", errors="replace"))
        content = raw["choices"][0]["message"]["content"]
        judged = json.loads(content)
        if isinstance(judged, dict) and all(field in judged for field in SCORE_FIELDS):
            judged["total_score"] = int(judged.get("total_score", sum(int(judged[field]) for field in SCORE_FIELDS)))
            judged["judge"] = "llm"
            return judged
    except Exception as exc:
        LOGGER.warning("LLM judge failed, using rule score: %s", exc)
    return fallback


def evaluate(args: argparse.Namespace) -> list[dict[str, Any]]:
    output_dir = ensure_output_dir(args.output_dir)
    questions = {item["id"]: item for item in read_json(output_dir / "questions.json", default=[])}
    results = iter_jsonl(output_dir / "results.jsonl")
    scored_rows: list[dict[str, Any]] = []

    scored_path = output_dir / "scored_results.jsonl"
    with scored_path.open("w", encoding="utf-8") as handle:
        for record in results:
            question = questions.get(record.get("question_id"), {})
            score = rule_score(question, record)
            if args.judge == "llm" and not record.get("error_message"):
                score = llm_judge(question, record, score)
            row = {**record, **score}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            scored_rows.append(row)

    write_csv(output_dir / "results.csv", scored_rows)
    return scored_rows


def main() -> None:
    load_dotenv_file(".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Score LightRAG mode-comparison results.")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--judge", choices=["rule", "llm"], default="rule")
    args = parser.parse_args()
    rows = evaluate(args)
    print(f"Wrote {len(rows)} scored rows to {Path(args.output_dir) / 'scored_results.jsonl'}")


if __name__ == "__main__":
    main()
