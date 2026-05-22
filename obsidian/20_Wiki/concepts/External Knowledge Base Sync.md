---
type: concept
status: seedling
created: 2026-05-22
updated: 2026-05-22
aliases:
  - K-Engine Sync
  - 外部知识库同步
sources:
  - "[[2026-05-20-graphrag-capability-commit]]"
tags:
  - type/concept
  - domain/lightrag
  - domain/kb-sync
provenance:
  extracted: 5
  inferred: 4
  ambiguous: 1
summary: "Local docs and scripts for syncing memories, conversations, and RAG test materials into an external knowledge base."
---

# External Knowledge Base Sync

## Summary

[[External Knowledge Base Sync]] captures the local knowledge materials under
`rag_test/`, `rag_eval/`, and `obsidian/`. The scripts support exporting memories
or conversations into Markdown batches and optionally importing them into an
external K-Engine knowledge base when the required environment variables are
present. ^[extracted]

## Core Ideas

- `rag_test/scripts/sync_memories_to_kb.py` reads MemOS memory records and renders
  Markdown export batches before optional K-Engine import. ^[extracted]
- `rag_test/scripts/sync_conversations_to_kb.py` normalizes Codex / Claude /
  OpenClaw conversations and masks common sensitive patterns by default. ^[extracted]
- `rag_eval/` provides standalone scripts for question generation, multi-mode
  LightRAG querying, scoring, reporting, and visualization. ^[extracted]
- `rag_test/rag-test-docs/` contains sample knowledge documents used for RAG and
  GraphRAG validation. ^[extracted]
- External upload should remain explicit because it can send memory or conversation
  data outside the repository. ^[inferred]

## Upload Boundary

The repository should track source scripts, docs, seed cases, and evaluation
artifacts that are useful for reproducing the workflow. It should not track local
`.env`, generated `__pycache__/`, runtime state, or build directories. ^[inferred]

## Related Notes

- [[Retrieval Harness Strategy]]
- [[GraphRAG Capability Layer]]
- [[LightRAG Project Navigation]]
- [[LightRAG Capability Navigation]]

## Open Questions

- Which external K-Engine repository should be treated as the canonical remote
  knowledge base for future sync runs? ^[ambiguous]
