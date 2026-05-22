---
type: map
status: active
created: 2026-05-20
updated: 2026-05-22
sources:
  - "[[2026-05-20-graphrag-capability-commit]]"
tags:
  - type/map
  - domain/lightrag
provenance:
  extracted: 8
  inferred: 6
  ambiguous: 0
summary: "Knowledge graph map of yesterday's GraphRAG capability work and the next implementation goals."
---

# LightRAG GraphRAG Capability Knowledge Graph

## Graph View

```mermaid
graph TD
  Project["[[LightRAG GraphRAG Capability Development]]"]
  Goal["[[LightRAG Next Goals]]"]
  Layer["[[GraphRAG Capability Layer]]"]
  Tools["[[Agent Tooling Surface]]"]
  Safety["[[Bounded Agent Autonomy]]"]
  MCP["[[MCP Adapter Goal]]"]
  Harness["[[Retrieval Harness Strategy]]"]
  Sync["[[External Knowledge Base Sync]]"]
  Raw["[[2026-05-20-graphrag-capability-commit]]"]

  Raw -->|documents| Project
  Project -->|implemented| Layer
  Layer -->|exposes| Tools
  Layer -->|enforces| Safety
  Tools -->|future protocol wrapper| MCP
  Goal -->|next candidate| MCP
  Goal -->|builds on| Layer
  Harness -->|evaluates| Layer
  Sync -->|supplies test material| Harness
```

## Relationship Triples

- [[2026-05-20-graphrag-capability-commit]] -> documents -> [[LightRAG GraphRAG Capability Development]] ^[extracted]
- [[LightRAG GraphRAG Capability Development]] -> implemented -> [[GraphRAG Capability Layer]] ^[extracted]
- [[GraphRAG Capability Layer]] -> exposes -> [[Agent Tooling Surface]] ^[extracted]
- [[GraphRAG Capability Layer]] -> enforces -> [[Bounded Agent Autonomy]] ^[extracted]
- [[Agent Tooling Surface]] -> can be wrapped by -> [[MCP Adapter Goal]] ^[inferred]
- [[LightRAG Next Goals]] -> likely next step -> [[MCP Adapter Goal]] ^[inferred]
- [[Retrieval Harness Strategy]] -> evaluates -> [[GraphRAG Capability Layer]] ^[inferred]
- [[External Knowledge Base Sync]] -> supplies test material -> [[Retrieval Harness Strategy]] ^[inferred]

## Sources

- [[2026-05-20-graphrag-capability-commit]]

## Related Notes

- [[index|LightRAG LLM Wiki Index]]
- [[LightRAG Capability Navigation]]
- [[LightRAG Project Navigation]]
- [[GraphRAG Capability Layer]]
- [[Agent Tooling Surface]]
- [[Bounded Agent Autonomy]]
- [[MCP Adapter Goal]]
- [[Retrieval Harness Strategy]]
- [[External Knowledge Base Sync]]
