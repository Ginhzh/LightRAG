---
type: concept
status: seedling
created: 2026-05-20
updated: 2026-05-20
aliases:
  - MCP 封装目标
sources:
  - "[[2026-05-20-graphrag-capability-commit]]"
tags:
  - type/concept
  - domain/mcp
  - domain/lightrag
provenance:
  extracted: 2
  inferred: 4
  ambiguous: 1
summary: "A likely next step: wrap the GraphRAG capability layer as an MCP-accessible tool surface without moving retrieval logic into the protocol layer."
---

# MCP Adapter Goal

## Summary

[[MCP Adapter Goal]] is the next architectural target after the first GraphRAG capability commit. The commit explicitly avoided adding MCP runtime dependencies, but it added tool schema metadata and a reusable capability layer that can be wrapped later. ^[inferred]

## Core Ideas

- The first version supports LLM/tool callers without adding MCP runtime dependencies. ^[extracted]
- Protocol adapters should stay thin and should not own retrieval logic. ^[extracted]
- A future MCP adapter should call [[GraphRAG Capability Layer]] methods rather than duplicate graph/RAG logic. ^[inferred]
- A direct tool-calling adapter may be useful before a full MCP server. ^[inferred]

## Why It Matters

MCP would let external Agent clients discover and call GraphRAG tools through a standard protocol. This aligns with the user's next-step question about MCP wrapping. ^[inferred]

## Key Claims

- The current implementation is not yet an MCP runtime server. ^[extracted]
- Tool schema metadata exists as a bridge toward future tool adapters. ^[inferred]

## Compared With

- [[Agent Tooling Surface]] — the tool surface MCP would expose.
- [[GraphRAG Capability Layer]] — the implementation MCP should delegate to.

## Sources

- [[2026-05-20-graphrag-capability-commit]]

## Related Notes

- [[index|LightRAG LLM Wiki Index]]
- [[LightRAG Capability Navigation]]
- [[LightRAG Project Navigation]]
- [[LightRAG GraphRAG Capability Knowledge Graph]]
- [[LightRAG Next Goals]]

## Open Questions

- Should the next milestone implement `GraphRAGToolAdapter` first, then an MCP server? ^[ambiguous]
