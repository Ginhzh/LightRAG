from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from rag_eval.common import SCORE_FIELDS, ensure_output_dir, env_summary, iter_jsonl, load_dotenv_file, read_json


def _avg(values: list[float]) -> float:
    return round(mean(values), 2) if values else 0.0


def aggregate_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_type_mode_rows: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        mode = str(row.get("query_mode", "unknown"))
        qtype = str(row.get("question_type", "unknown"))
        by_mode_rows[mode].append(row)
        by_type_mode_rows[qtype][mode].append(row)

    by_mode: dict[str, dict[str, float]] = {}
    for mode, items in by_mode_rows.items():
        count = len(items)
        errors = sum(1 for item in items if item.get("error_message"))
        by_mode[mode] = {
            "count": count,
            "avg_total_score": _avg([float(item.get("total_score", 0)) for item in items]),
            "avg_boundary_score": _avg([float(item.get("boundary_score", 0)) for item in items]),
            "avg_relation_score": _avg([float(item.get("relation_score", 0)) for item in items]),
            "avg_causal_score": _avg([float(item.get("causal_score", 0)) for item in items]),
            "error_rate": round(errors / count, 4) if count else 0.0,
        }

    best_by_type: dict[str, str] = {}
    by_type: dict[str, dict[str, float]] = {}
    for qtype, mode_map in by_type_mode_rows.items():
        type_summary = {
            mode: _avg([float(item.get("total_score", 0)) for item in items])
            for mode, items in mode_map.items()
        }
        by_type[qtype] = type_summary
        if type_summary:
            best_by_type[qtype] = max(type_summary, key=type_summary.get)

    return {"by_mode": by_mode, "by_type": by_type, "best_by_type": best_by_type}


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _select_cases(rows: list[dict[str, Any]], limit: int = 5) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("question_id", ""))].append(row)
    ranked = []
    for question_id, items in grouped.items():
        scores = [float(item.get("total_score", 0)) for item in items]
        spread = max(scores) - min(scores) if scores else 0
        flags = sum(len(item.get("flags", [])) for item in items if isinstance(item.get("flags"), list))
        ranked.append((spread + flags, question_id, items))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [(question_id, items) for _, question_id, items in ranked[:limit]]


def build_report(args: argparse.Namespace) -> str:
    load_dotenv_file(".env")
    output_dir = ensure_output_dir(args.output_dir)
    rows = iter_jsonl(output_dir / "scored_results.jsonl")
    questions = {item["id"]: item for item in read_json(output_dir / "questions.json", default=[])}
    summary = aggregate_scores(rows)
    env_config = env_summary()
    model_config = args.model_config or "; ".join(
        f"{key}={value}" for key, value in env_config.items() if key.startswith("LLM_")
    )
    embedding_config = args.embedding_config or "; ".join(
        f"{key}={value}" for key, value in env_config.items() if key.startswith("EMBEDDING_")
    )
    storage_config = "; ".join(
        f"{key}={value}"
        for key, value in env_config.items()
        if key in {"WORKING_DIR", "INPUT_DIR", "LIGHTRAG_GRAPH_STORAGE", "LIGHTRAG_VECTOR_STORAGE", "RERANK_BINDING"}
    )
    created_at_values = sorted(str(row.get("created_at")) for row in rows if row.get("created_at"))
    if created_at_values:
        execution_time = f"{created_at_values[0]} 至 {created_at_values[-1]}"
    else:
        execution_time = "无已评分结果；请先运行查询和评分。"

    lines: list[str] = []
    lines.append("# LightRAG 查询模式自动评测报告")
    lines.append("")
    lines.append("## 实验配置")
    lines.append("")
    lines.append(f"- 文档集合：{args.document_set}")
    lines.append(f"- 模型配置：{model_config or '未从 .env 读取到'}")
    lines.append(f"- Embedding 配置：{embedding_config or '未从 .env 读取到'}")
    lines.append(f"- Storage/Rerank 配置：{storage_config or '未从 .env 读取到'}")
    lines.append(f"- 查询模式：{', '.join(sorted(summary['by_mode'])) or args.modes}")
    lines.append(f"- 问题数量：{len(questions)}")
    lines.append(f"- 执行时间：{execution_time}")
    lines.append(f"- 结果来源：`{output_dir / 'scored_results.jsonl'}`")
    lines.append("")

    lines.append("## 总体评分表")
    lines.append("")
    lines.append(
        _markdown_table(
            ["模式", "样本数", "平均总分", "Boundary", "Relation", "Causal", "错误率"],
            [
                [
                    mode,
                    data["count"],
                    data["avg_total_score"],
                    data["avg_boundary_score"],
                    data["avg_relation_score"],
                    data["avg_causal_score"],
                    data["error_rate"],
                ]
                for mode, data in sorted(summary["by_mode"].items())
            ],
        )
    )
    lines.append("")

    lines.append("## 按问题类型分析")
    lines.append("")
    for qtype, mode_scores in sorted(summary["by_type"].items()):
        best = summary["best_by_type"].get(qtype, "无")
        score_text = ", ".join(f"{mode}: {score}" for mode, score in sorted(mode_scores.items()))
        lines.append(f"- `{qtype}`：当前平均分最高模式为 `{best}`；各模式平均分：{score_text}。")
    if "timeline_boundary" in summary["by_type"]:
        leak_rows = [
            row
            for row in rows
            if row.get("question_type") == "timeline_boundary"
            and isinstance(row.get("flags"), list)
            and "possible_timeline_leak" in row["flags"]
        ]
        leak_counts: dict[str, int] = defaultdict(int)
        for row in leak_rows:
            leak_counts[str(row.get("query_mode"))] += 1
        if leak_counts:
            worst = max(leak_counts, key=leak_counts.get)
            lines.append(f"- `timeline_boundary`：当前最容易被规则初筛标记越界的模式是 `{worst}`。")
    lines.append("")

    lines.append("## 典型案例分析")
    lines.append("")
    for question_id, items in _select_cases(rows, limit=5):
        question = questions.get(question_id, {})
        lines.append(f"### {question_id} {question.get('type', '')}")
        lines.append("")
        lines.append(f"- 问题：{question.get('question', items[0].get('question', ''))}")
        sorted_items = sorted(items, key=lambda item: float(item.get("total_score", 0)), reverse=True)
        best = sorted_items[0] if sorted_items else {}
        worst = sorted_items[-1] if sorted_items else {}
        lines.append(f"- 最好模式：`{best.get('query_mode', '无')}`，总分 {best.get('total_score', 0)}。")
        lines.append(f"- 最差模式：`{worst.get('query_mode', '无')}`，总分 {worst.get('total_score', 0)}。")
        for item in sorted(items, key=lambda row: str(row.get("query_mode"))):
            flags = item.get("flags", [])
            flag_text = ",".join(flags) if isinstance(flags, list) else str(flags)
            lines.append(f"- `{item.get('query_mode')}`：{_short(item.get('answer', '') or item.get('error_message', ''))}（flags: {flag_text or '无'}）")
        lines.append("- 差异原因：规则初筛主要依据相关性、关系链、因果链、边界控制和检索上下文返回量；需人工复核高风险案例。")
        lines.append("")

    lines.append("## 重点观察")
    lines.append("")
    lines.extend(
        [
            "- naive：重点检查是否事实短答准确但缺少关系链，或召回语义相似但时间线错误的片段。",
            "- local：重点检查人物、地点、物品的直接关系是否更稳，以及是否过窄。",
            "- global：重点检查是否回答过宽，或是否能通过事件/关系节点更好聚焦。",
            "- hybrid：重点检查是否兼顾事件细节和图谱关系，特别是因果链问题。",
            "- mix：重点检查原文细节与图谱关系共同参与时是否更稳。",
            "- 特别关注“答案丰富但边界错”“答案短但忠于上下文”“Graph-RAG 有关系但缺原文证据”“图谱实体抽取错误导致偏移”等现象。",
        ]
    )
    lines.append("")

    lines.append("## 结论")
    lines.append("")
    for mode in ["naive", "local", "global", "hybrid", "mix"]:
        data = summary["by_mode"].get(mode)
        if not data:
            lines.append(f"- `{mode}`：本轮没有有效样本。")
            continue
        lines.append(
            f"- `{mode}`：平均总分 {data['avg_total_score']}，boundary {data['avg_boundary_score']}，relation {data['avg_relation_score']}，causal {data['avg_causal_score']}，错误率 {data['error_rate']}。"
        )
    lines.append("- 推荐：先用本报告定位问题类型差异，再针对低分类型调整 chunk、实体抽取、rerank、提示词和时间线边界约束。")
    lines.append("")

    report = "\n".join(lines)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a markdown report for LightRAG mode evaluation.")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--document-set", default="诡秘之主(501-1000章).txt")
    parser.add_argument("--model-config", default="")
    parser.add_argument("--embedding-config", default="")
    parser.add_argument("--modes", default="naive,local,global,hybrid,mix")
    args = parser.parse_args()
    build_report(args)
    print(f"Wrote report to {Path(args.output_dir) / 'report.md'}")


if __name__ == "__main__":
    main()
