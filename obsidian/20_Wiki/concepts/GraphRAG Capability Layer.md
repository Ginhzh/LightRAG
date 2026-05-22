---
type: concept
status: seedling
created: 2026-05-20
updated: 2026-05-20
aliases:
  - GraphRAG 能力层
sources:
  - "[[2026-05-20-graphrag-capability-commit]]"
tags:
  - type/concept
  - domain/lightrag
provenance:
  extracted: 7
  inferred: 2
  ambiguous: 0
summary: "A thin reusable layer that exposes LightRAG query and read-only graph/RAG retrieval capabilities to application and Agent callers."
---

# GraphRAG Capability Layer

## Summary

[[GraphRAG Capability Layer]] is the first-pass wrapper around existing LightRAG query and storage surfaces. It exists to reuse `aquery_data()` and `aquery_llm()` while exposing read-only tools for Agent exploration without changing indexing, graph-building, storage adapters, or existing `/query` behavior. ^[extracted]

## Core Ideas

- The capability layer is intentionally outside the graph-building and storage internals. ^[extracted]
- `ask()` wraps high-level answer generation through `aquery_llm()`. ^[extracted]
- `retrieve()` wraps structured evidence retrieval through `aquery_data()`. ^[extracted]
- The toolbox exposes `search_entities`, `search_relationships`, `search_chunks`, `expand_neighbors`, and `retrieve_context`. ^[extracted]
- REST routes live under `/graphrag/*`, leaving existing `/query` behavior independent. ^[extracted]
- The layer is designed as the reusable core for future protocol adapters such as [[MCP Adapter Goal]]. ^[inferred]

## Why It Matters

This layer lets the project move toward Agent-callable GraphRAG without requiring the user to understand or modify the lower-level RAG and graph construction logic. ^[inferred]

## Key Claims

- The commit added `lightrag/capabilities/graph_rag.py` as the main capability implementation. ^[extracted]
- The commit added `lightrag/api/routers/graphrag_routes.py` as the REST API surface. ^[extracted]
- The implementation was tested with `./scripts/test.sh tests/test_graphrag_capability.py tests/test_graphrag_routes.py`. ^[extracted]

## Compared With

- [[Agent Tooling Surface]] — the capability layer contains both business-facing wrappers and Agent-facing tools.
- [[Bounded Agent Autonomy]] — the capability layer enforces the budget and safety limits.
- [[MCP Adapter Goal]] — MCP should wrap this layer rather than duplicate its logic.

## Sources

- [[2026-05-20-graphrag-capability-commit]] — commit narrative, changed files, constraints, tests.

## Related Notes

- [[index|LightRAG LLM Wiki Index]]
- [[LightRAG Capability Navigation]]
- [[LightRAG Project Navigation]]
- [[LightRAG GraphRAG Capability Development]]
- [[LightRAG GraphRAG Capability Knowledge Graph]]
- [[LightRAG Next Goals]]

## Open Questions

- Should future MCP support be a minimal server in this repo or an external adapter package?
