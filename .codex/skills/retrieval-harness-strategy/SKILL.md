---
name: retrieval-harness-strategy
description: Use when running or revising the LightRAG retrieval harness after real evaluation rounds expose strategy gaps, weak multi-hop relation hits, baseline answer extraction issues, or harness-vs-naive/mix comparison drift.
---

# Retrieval Harness Strategy

## Core Rule

Treat harness success as answer-quality evidence only when the run produces:

- independent entity, relationship, and chunk evidence
- a short final answer text suitable for scoring
- traceable coverage of every `subject_hint` and `related_hints` item

Transport health alone is not enough.

## Required Exploration Pattern

1. Check `.env`, `data/rag_storage`, and embedding endpoint health first.
   Known endpoint: `http://10.12.222.108:8001/v1`.
2. Run entity, relationship, and chunk explorers independently.
3. For relation questions, search every related hint:
   - `{subject_hint} {related_hint}` for each hint
   - `{subject_hint} {full_question}` as a catch-all
4. Run weak-link expansion when relation evidence is partial:
   - expand `subject_hint`
   - expand every `related_hint`
   - expand first-round relation endpoints
   - keep depth bounded to 1-2 and cap seeds
5. Retrieve context only after fine-grained evidence is merged.
6. Ask for a non-streaming final answer and store both raw JSON and extracted answer text.
7. Compare harness against `naive` and `mix` using answer text, not raw context dumps.

## Round-3 Lessons

Strong hits validate the multi-index protocol, not final superiority:

- `adv-round3-001`: 奥黛丽 -> 赫温·兰比斯
- `adv-round3-002`: 埃姆林 -> 月亮
- `adv-round3-005`: 伦纳德 -> 帕列斯
- `adv-round3-008`: 班西港 -> 梅迪奇 / 恶灵

Partial or weak hits require full-hint and weak-link handling:

- `adv-round3-006`: must cover 白骨信使 / 阿兹克 / 铜哨 / 黑皇帝牌
- `adv-round3-007`: must cover 格尔曼斯帕罗 / 达尼兹 / 冰山中将 / 黄金梦想号
- `adv-round3-003`: avoid collapsing 阿尔杰 into 倒吊人-only strong edges
- `adv-round3-004`: recover 神秘女王 / 贝尔纳黛 main chain
- `adv-round3-009`: include 阿蒙分身 judgment, not only 身份 / 途径
- `adv-round3-010`: include 光之祭司 / 神弃之地 / 建议链

## Harness Editing Checklist

- Add failing tests before changing strategy code.
- Keep query expansion bounded and deterministic.
- Do not hide weak retrieval by marking transport-only success as answer success.
- Preserve raw MCP payloads for debugging.
- Keep `answer_text` / `final_answer_text` populated for automatic scoring.

## Verification

Minimum local checks:

```bash
cargo test
uv run python -m unittest experiments/retrieval-harness-rs/python/test_run_baseline.py
```

For real retrieval checks, also use `$mcp-retrieval-verification`.
