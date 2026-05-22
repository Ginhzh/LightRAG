---
type: concept
status: seedling
created: 2026-05-22
updated: 2026-05-22
aliases:
  - Rust Retrieval Harness
  - 检索评测 Harness
sources:
  - "[[2026-05-20-graphrag-capability-commit]]"
tags:
  - type/concept
  - domain/lightrag
  - domain/retrieval
provenance:
  extracted: 6
  inferred: 4
  ambiguous: 1
summary: "A Rust experiment harness that compares LightRAG baseline modes with bounded GraphRAG-style retrieval exploration."
---

# Retrieval Harness Strategy

## Summary

[[Retrieval Harness Strategy]] is the local Rust framework under
`experiments/retrieval-harness-rs/`. It evaluates retrieval behavior by running
baseline LightRAG modes and a bounded harness path that explores entities,
relationships, and chunks before asking for a final answer. ^[extracted]

## Core Ideas

- The harness models evaluation cases with `question`, `question_type`,
  `subject_hint`, `related_hints`, and optional expected answers. ^[extracted]
- Baseline runs compare `local`, `global`, `hybrid`, `naive`, and `mix` modes. ^[extracted]
- Harness runs split exploration into entity, relationship, and chunk explorers. ^[extracted]
- The orchestrator merges evidence and only retrieves context / asks for a final
  answer when evidence is sufficient. ^[extracted]
- Query strategy should search every related hint for relation-heavy questions and
  preserve answer text for scoring. ^[inferred]

## Why It Matters

The harness creates a repeatable bridge between [[GraphRAG Capability Layer]] and
real answer-quality evaluation. It avoids treating transport success as retrieval
success and keeps raw evidence available for debugging weak multi-hop cases.
^[inferred]

## Key Files

- `experiments/retrieval-harness-rs/src/orchestrator.rs` coordinates explorers and
  final answer calls. ^[extracted]
- `experiments/retrieval-harness-rs/src/types.rs` defines evaluation cases, baseline
  runs, evidence bundles, and suite results. ^[extracted]
- `experiments/retrieval-harness-rs/config/default.toml` points to default case and
  MCP helper paths. ^[extracted]
- `experiments/retrieval-harness-rs/cases/*.json` stores seed, hard, and adversarial
  evaluation cases. ^[extracted]

## Verification Notes

Minimum local checks are `cargo test` in `experiments/retrieval-harness-rs/` and
`uv run python -m unittest experiments/retrieval-harness-rs/python/test_run_baseline.py`.
Real retrieval validation still depends on a live LightRAG / MCP setup. ^[inferred]

## Related Notes

- [[GraphRAG Capability Layer]]
- [[Agent Tooling Surface]]
- [[External Knowledge Base Sync]]
- [[LightRAG Project Navigation]]
- [[LightRAG Next Goals]]

## Open Questions

- Which cases should become the canonical regression set before upstreaming this
  experiment? ^[ambiguous]
