from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from rag_eval.common import SCORE_FIELDS, ensure_output_dir, iter_jsonl, read_json


MODE_ORDER = ["naive", "local", "global", "hybrid", "mix"]
TYPE_LABELS = {
    "fact": "单点事实",
    "local_relation": "局部关系",
    "global_relation": "全局关系",
    "causal_chain": "因果链",
    "timeline_boundary": "时间线边界",
    "state_reasoning": "状态推理",
    "anti_pollution": "反污染",
}


def _avg(values: list[float]) -> float:
    return round(mean(values), 2) if values else 0.0


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _context_counts(context: dict[str, Any]) -> dict[str, int]:
    data = context.get("data") if isinstance(context, dict) else {}
    if not isinstance(data, dict):
        return {"entities": 0, "relationships": 0, "chunks": 0, "references": 0}
    return {
        "entities": len(data.get("entities", []) if isinstance(data.get("entities"), list) else []),
        "relationships": len(data.get("relationships", []) if isinstance(data.get("relationships"), list) else []),
        "chunks": len(data.get("chunks", []) if isinstance(data.get("chunks"), list) else []),
        "references": len(data.get("references", []) if isinstance(data.get("references"), list) else []),
    }


def build_dashboard_data(rows: list[dict[str, Any]], questions: list[dict[str, Any]]) -> dict[str, Any]:
    questions_by_id = {item["id"]: item for item in questions}
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_type_mode: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    flags_by_mode: dict[str, Counter[str]] = defaultdict(Counter)
    latency_by_mode: dict[str, list[float]] = defaultdict(list)

    slim_rows: list[dict[str, Any]] = []
    for row in rows:
        mode = str(row.get("query_mode", "unknown"))
        qtype = str(row.get("question_type", "unknown"))
        by_mode[mode].append(row)
        by_type_mode[qtype][mode].append(row)
        latency_by_mode[mode].append(float(row.get("latency_ms") or 0))
        for flag in row.get("flags", []) if isinstance(row.get("flags"), list) else []:
            flags_by_mode[mode][str(flag)] += 1

        counts = _context_counts(row.get("retrieved_context", {}))
        slim_rows.append(
            {
                "question_id": row.get("question_id"),
                "question": row.get("question"),
                "question_type": qtype,
                "type_label": TYPE_LABELS.get(qtype, qtype),
                "expected_strength": row.get("expected_strength"),
                "query_mode": mode,
                "answer": _truncate(str(row.get("answer") or row.get("error_message") or ""), 700),
                "answer_full": str(row.get("answer") or row.get("error_message") or ""),
                "latency_ms": round(float(row.get("latency_ms") or 0), 2),
                "error_message": row.get("error_message", ""),
                "flags": row.get("flags", []),
                "context_counts": counts,
                "total_score": row.get("total_score", 0),
                **{field: row.get(field, 0) for field in SCORE_FIELDS},
            }
        )

    mode_summary = []
    for mode in MODE_ORDER:
        items = by_mode.get(mode, [])
        if not items:
            continue
        mode_summary.append(
            {
                "mode": mode,
                "count": len(items),
                "avg_total_score": _avg([float(item.get("total_score", 0)) for item in items]),
                "avg_latency_ms": _avg(latency_by_mode[mode]),
                "error_count": sum(1 for item in items if item.get("error_message")),
                **{
                    f"avg_{field}": _avg([float(item.get(field, 0)) for item in items])
                    for field in SCORE_FIELDS
                },
            }
        )

    type_summary = []
    for qtype in sorted(by_type_mode):
        for mode in MODE_ORDER:
            items = by_type_mode[qtype].get(mode, [])
            if not items:
                continue
            type_summary.append(
                {
                    "question_type": qtype,
                    "type_label": TYPE_LABELS.get(qtype, qtype),
                    "mode": mode,
                    "avg_total_score": _avg([float(item.get("total_score", 0)) for item in items]),
                    "count": len(items),
                }
            )

    all_flags = sorted({flag for counter in flags_by_mode.values() for flag in counter})
    flag_summary = [
        {"mode": mode, **{flag: flags_by_mode[mode].get(flag, 0) for flag in all_flags}}
        for mode in MODE_ORDER
        if mode in by_mode
    ]

    question_summary = []
    for qid in sorted(questions_by_id):
        items = [item for item in slim_rows if item["question_id"] == qid]
        if not items:
            continue
        best = max(items, key=lambda item: item["total_score"])
        worst = min(items, key=lambda item: item["total_score"])
        question = questions_by_id[qid]
        question_summary.append(
            {
                "question_id": qid,
                "question": question["question"],
                "question_type": question["type"],
                "type_label": TYPE_LABELS.get(question["type"], question["type"]),
                "expected_strength": question.get("expected_strength"),
                "best_mode": best["query_mode"],
                "best_score": best["total_score"],
                "worst_mode": worst["query_mode"],
                "worst_score": worst["total_score"],
                "spread": best["total_score"] - worst["total_score"],
            }
        )

    return {
        "mode_order": MODE_ORDER,
        "score_fields": SCORE_FIELDS,
        "mode_summary": mode_summary,
        "type_summary": type_summary,
        "flag_summary": flag_summary,
        "questions": question_summary,
        "rows": slim_rows,
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LightRAG 模式评测可视化</title>
  <style>
    :root {
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #64748b;
      --line: #d8dee8;
      --accent: #2563eb;
      --bad: #dc2626;
      --warn: #d97706;
      --good: #15803d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      letter-spacing: 0;
    }
    header {
      padding: 24px 32px 16px;
      border-bottom: 1px solid var(--line);
      background: #fff;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    h1 { margin: 0 0 8px; font-size: 24px; line-height: 1.2; }
    h2 { margin: 0 0 14px; font-size: 18px; }
    h3 { margin: 0 0 10px; font-size: 15px; }
    .sub { color: var(--muted); font-size: 13px; }
    main { padding: 24px 32px 40px; display: grid; gap: 18px; }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      min-width: 0;
    }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 18px; }
    .span-4 { grid-column: span 4; }
    .span-6 { grid-column: span 6; }
    .span-8 { grid-column: span 8; }
    .span-12 { grid-column: span 12; }
    .metric-row { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
    .metric {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #fbfcfe;
    }
    .metric strong { display: block; font-size: 22px; margin-top: 4px; }
    .metric span { color: var(--muted); font-size: 12px; }
    .bar-chart { display: grid; gap: 10px; }
    .bar-line { display: grid; grid-template-columns: 72px 1fr 52px; gap: 10px; align-items: center; font-size: 13px; }
    .bar-bg { height: 18px; background: #eef2f7; border-radius: 4px; overflow: hidden; }
    .bar { height: 100%; background: var(--accent); }
    .bar.local { background: #059669; }
    .bar.global { background: #7c3aed; }
    .bar.hybrid { background: #ea580c; }
    .bar.mix { background: #0891b2; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; background: #fbfcfe; position: sticky; top: 88px; z-index: 2; }
    .filters { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
    select, input {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 13px;
      background: #fff;
      min-height: 36px;
    }
    input { min-width: 280px; }
    .pill {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      background: #eef2f7;
      color: #334155;
      margin: 0 4px 4px 0;
      white-space: nowrap;
    }
    .pill.warn { background: #fff7ed; color: var(--warn); }
    .pill.bad { background: #fef2f2; color: var(--bad); }
    details {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fbfcfe;
      margin-bottom: 8px;
    }
    summary { cursor: pointer; font-weight: 600; }
    .answer {
      margin-top: 8px;
      white-space: pre-wrap;
      color: #334155;
      line-height: 1.55;
      font-size: 13px;
    }
    .small { font-size: 12px; color: var(--muted); }
    .heat {
      display: grid;
      grid-template-columns: 120px repeat(5, 1fr);
      gap: 1px;
      background: var(--line);
      border: 1px solid var(--line);
      overflow: hidden;
      border-radius: 6px;
      font-size: 12px;
    }
    .heat div { background: #fff; padding: 8px; min-height: 34px; }
    .heat .head { background: #f1f5f9; color: #475569; font-weight: 600; }
    .heat .cell { text-align: center; }
    @media (max-width: 960px) {
      header { padding: 18px; }
      main { padding: 18px; }
      .span-4, .span-6, .span-8 { grid-column: span 12; }
      .metric-row { grid-template-columns: 1fr; }
      input { min-width: 100%; }
      .heat { grid-template-columns: 96px repeat(5, 1fr); overflow-x: auto; }
    }
  </style>
</head>
<body>
  <header>
    <h1>LightRAG 查询模式评测可视化</h1>
    <div class="sub">数据来源：outputs/scored_results.jsonl；页面内嵌精简摘要，不包含完整 raw_response。</div>
  </header>
  <main>
    <section class="span-12">
      <h2>总体概览</h2>
      <div id="metrics" class="metric-row"></div>
    </section>
    <div class="grid">
      <section class="span-6">
        <h2>模式平均总分</h2>
        <div id="modeBars" class="bar-chart"></div>
      </section>
      <section class="span-6">
        <h2>平均延迟</h2>
        <div id="latencyBars" class="bar-chart"></div>
      </section>
      <section class="span-8">
        <h2>问题类型 × 模式</h2>
        <div id="typeHeat" class="heat"></div>
      </section>
      <section class="span-4">
        <h2>风险 Flags</h2>
        <div id="flagTable"></div>
      </section>
      <section class="span-12">
        <h2>问题表现排行</h2>
        <div class="filters">
          <select id="typeFilter"><option value="">全部类型</option></select>
          <select id="modeFilter"><option value="">全部模式</option></select>
          <input id="searchInput" placeholder="搜索问题、答案或 flag">
        </div>
        <div id="questionList"></div>
      </section>
    </div>
  </main>
  <script id="dashboard-data" type="application/json">__DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById('dashboard-data').textContent);
    const modeClasses = {naive: 'naive', local: 'local', global: 'global', hybrid: 'hybrid', mix: 'mix'};
    const fmt = (n) => Number(n || 0).toLocaleString('zh-CN', {maximumFractionDigits: 2});

    function renderMetrics() {
      const rows = data.rows;
      const errors = rows.filter(r => r.error_message).length;
      const best = [...data.mode_summary].sort((a, b) => b.avg_total_score - a.avg_total_score)[0];
      const leak = rows.filter(r => (r.flags || []).includes('possible_timeline_leak')).length;
      const html = [
        ['总样本', rows.length],
        ['最佳模式', `${best.mode} (${best.avg_total_score})`],
        ['错误数', errors],
        ['时间线风险', leak],
        ['问题数', data.questions.length],
      ].map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('');
      document.getElementById('metrics').innerHTML = html;
    }

    function renderBars(id, items, valueKey, maxValue) {
      const max = maxValue || Math.max(...items.map(item => item[valueKey]), 1);
      document.getElementById(id).innerHTML = items.map(item => {
        const width = Math.max(2, item[valueKey] / max * 100);
        return `<div class="bar-line"><div>${item.mode}</div><div class="bar-bg"><div class="bar ${modeClasses[item.mode] || ''}" style="width:${width}%"></div></div><div>${fmt(item[valueKey])}</div></div>`;
      }).join('');
    }

    function renderTypeHeat() {
      const modes = data.mode_order;
      const types = [...new Set(data.type_summary.map(item => item.question_type))].sort();
      const map = new Map(data.type_summary.map(item => [`${item.question_type}:${item.mode}`, item.avg_total_score]));
      const cells = [`<div class="head">问题类型</div>`, ...modes.map(mode => `<div class="head">${mode}</div>`)];
      for (const type of types) {
        const label = data.type_summary.find(item => item.question_type === type)?.type_label || type;
        cells.push(`<div class="head">${label}</div>`);
        for (const mode of modes) {
          const value = map.get(`${type}:${mode}`) || 0;
          const alpha = Math.max(0.08, Math.min(0.9, value / 35));
          cells.push(`<div class="cell" style="background:rgba(37,99,235,${alpha});color:${alpha > 0.55 ? '#fff' : '#17202a'}">${fmt(value)}</div>`);
        }
      }
      document.getElementById('typeHeat').innerHTML = cells.join('');
    }

    function renderFlags() {
      const flags = [...new Set(data.flag_summary.flatMap(row => Object.keys(row).filter(key => key !== 'mode')))];
      let html = '<table><thead><tr><th>模式</th>' + flags.map(f => `<th>${f}</th>`).join('') + '</tr></thead><tbody>';
      html += data.flag_summary.map(row => '<tr><td>' + row.mode + '</td>' + flags.map(f => `<td>${row[f] || 0}</td>`).join('') + '</tr>').join('');
      html += '</tbody></table>';
      document.getElementById('flagTable').innerHTML = html;
    }

    function initFilters() {
      const typeSelect = document.getElementById('typeFilter');
      const modeSelect = document.getElementById('modeFilter');
      const typeSeen = new Map();
      data.questions.forEach(q => typeSeen.set(q.question_type, q.type_label));
      for (const [type, label] of [...typeSeen.entries()].sort()) {
        typeSelect.insertAdjacentHTML('beforeend', `<option value="${type}">${label}</option>`);
      }
      data.mode_order.forEach(mode => modeSelect.insertAdjacentHTML('beforeend', `<option value="${mode}">${mode}</option>`));
      [typeSelect, modeSelect, document.getElementById('searchInput')].forEach(el => el.addEventListener('input', renderQuestions));
    }

    function renderQuestions() {
      const type = document.getElementById('typeFilter').value;
      const mode = document.getElementById('modeFilter').value;
      const search = document.getElementById('searchInput').value.trim().toLowerCase();
      let questions = data.questions;
      if (type) questions = questions.filter(q => q.question_type === type);
      if (search) {
        questions = questions.filter(q => {
          const rows = data.rows.filter(r => r.question_id === q.question_id);
          const hay = [q.question, ...rows.map(r => r.answer), ...rows.flatMap(r => r.flags || [])].join(' ').toLowerCase();
          return hay.includes(search);
        });
      }
      questions = [...questions].sort((a, b) => b.spread - a.spread);
      document.getElementById('questionList').innerHTML = questions.map(q => {
        let rows = data.rows.filter(r => r.question_id === q.question_id);
        if (mode) rows = rows.filter(r => r.query_mode === mode);
        rows.sort((a, b) => data.mode_order.indexOf(a.query_mode) - data.mode_order.indexOf(b.query_mode));
        const answerHtml = rows.map(r => {
          const flags = (r.flags || []).map(f => `<span class="pill ${f.includes('leak') ? 'bad' : 'warn'}">${f}</span>`).join('') || '<span class="pill">无 flag</span>';
          const counts = r.context_counts || {};
          return `<details><summary>${r.query_mode} · ${r.total_score}/35 · ${fmt(r.latency_ms)}ms</summary>
            <div class="small">维度：boundary ${r.boundary_score} / relation ${r.relation_score} / causal ${r.causal_score}；上下文：E ${counts.entities || 0}, R ${counts.relationships || 0}, C ${counts.chunks || 0}, Ref ${counts.references || 0}</div>
            <div>${flags}</div>
            <div class="answer">${escapeHtml(r.answer)}</div>
          </details>`;
        }).join('');
        return `<section>
          <h3>${q.question_id} [${q.type_label}] ${escapeHtml(q.question)}</h3>
          <div class="small">预期优势：${q.expected_strength}；最好：${q.best_mode} ${q.best_score}；最差：${q.worst_mode} ${q.worst_score}；分差：${q.spread}</div>
          <div style="margin-top:10px">${answerHtml}</div>
        </section>`;
      }).join('');
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }

    renderMetrics();
    renderBars('modeBars', data.mode_summary, 'avg_total_score', 35);
    renderBars('latencyBars', data.mode_summary, 'avg_latency_ms');
    renderTypeHeat();
    renderFlags();
    initFilters();
    renderQuestions();
  </script>
</body>
</html>
"""


def write_dashboard(data: dict[str, Any], output_path: Path) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    content = HTML_TEMPLATE.replace("__DATA__", html.escape(payload, quote=False))
    output_path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a standalone HTML dashboard for LightRAG evaluation results.")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--output-file", default="dashboard.html")
    args = parser.parse_args()

    output_dir = ensure_output_dir(args.output_dir)
    rows = iter_jsonl(output_dir / "scored_results.jsonl")
    questions = read_json(output_dir / "questions.json", default=[])
    if not rows:
        raise SystemExit(f"No scored rows found at {output_dir / 'scored_results.jsonl'}")
    if not questions:
        raise SystemExit(f"No questions found at {output_dir / 'questions.json'}")

    data = build_dashboard_data(rows, questions)
    output_path = output_dir / args.output_file
    write_dashboard(data, output_path)
    print(f"Wrote dashboard to {output_path}")


if __name__ == "__main__":
    main()
