---
type: concept
status: seedling
created: 2026-05-20
updated: 2026-05-20
aliases:
  - Agent 工具面
sources:
  - "[[2026-05-20-graphrag-capability-commit]]"
tags:
  - type/concept
  - domain/agent
  - domain/lightrag
provenance:
  extracted: 4
  inferred: 2
  ambiguous: 0
summary: "The callable tool layer that lets an Agent inspect graph entities, relationships, chunks, neighbors, and retrieval context."
---

# Agent Tooling Surface

## Summary

[[Agent Tooling Surface]] is the set of GraphRAG tools exposed for LLM or Agent callers. It gives Agents controlled access to graph and RAG retrieval without letting them mutate storage or build graphs. ^[inferred]

## Core Ideas

- The committed toolbox exposes `search_entities`, `search_relationships`, `search_chunks`, `expand_neighbors`, and `retrieve_context`. ^[extracted]
- The tool surface is separate from the REST protocol and can later be wrapped by [[MCP Adapter Goal]]. ^[inferred]
- The implementation avoids MCP runtime dependencies in the first version. ^[extracted]
- Tool schema metadata is intended for LLM/tool callers. ^[extracted]

## Why It Matters

The user wants Agents to explore the graph when needed. This surface gives the Agent enough agency to inspect entities, relations, chunks, and neighbors while keeping the behavior bounded. ^[inferred]

## Key Claims

- Full A2A Agent was rejected in the first pass. ^[extracted]
- Protocol adapters should stay thin and not move retrieval logic out of [[GraphRAG Capability Layer]]. ^[extracted]

## Compared With

- [[GraphRAG Capability Layer]] — owns the actual Python methods.
- [[Bounded Agent Autonomy]] — defines limits for safe tool use.
- [[MCP Adapter Goal]] — future standard protocol wrapper for this tool surface.

## Sources

- [[2026-05-20-graphrag-capability-commit]]

## Related Notes

- [[index|LightRAG LLM Wiki Index]]
- [[LightRAG Capability Navigation]]
- [[LightRAG Project Navigation]]
- [[LightRAG GraphRAG Capability Knowledge Graph]]
- [[LightRAG Next Goals]]

## Open Questions

- Which external Agent runtime should be targeted first for tool calling compatibility?
