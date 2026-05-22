---
type: concept
status: seedling
created: 2026-05-20
updated: 2026-05-20
aliases:
  - 受控自主性
sources:
  - "[[2026-05-20-graphrag-capability-commit]]"
tags:
  - type/concept
  - domain/agent
  - domain/safety
provenance:
  extracted: 4
  inferred: 2
  ambiguous: 0
summary: "The safety model that lets Agents explore graph/RAG tools while enforcing hard budgets, traceability, and non-mutating access."
---

# Bounded Agent Autonomy

## Summary

[[Bounded Agent Autonomy]] is the safety boundary for allowing Agents to call GraphRAG tools. The current implementation exposes read-only tools with hard limits and trace metadata. ^[extracted]

## Core Ideas

- The capability commit states that graph-building and storage adapters must not be altered. ^[extracted]
- The toolbox is read-only and should not rewrite storage. ^[extracted]
- Trace metadata records tool use and supports review. ^[extracted]
- Hard autonomy limits reduce the risk of unlimited Agent exploration. ^[inferred]

## Why It Matters

Without explicit limits, Agentic graph exploration can become expensive, unstable, or difficult to audit. The bounded approach preserves control while still enabling exploration. ^[inferred]

## Key Claims

- Storage rewrite was rejected as out of scope. ^[extracted]
- Full repository tests and ruff were not completed in the recorded validation. ^[extracted]

## Compared With

- [[Agent Tooling Surface]] — autonomy applies to the tools an Agent can invoke.
- [[GraphRAG Capability Layer]] — enforces the limits in implementation.

## Sources

- [[2026-05-20-graphrag-capability-commit]]

## Related Notes

- [[index|LightRAG LLM Wiki Index]]
- [[LightRAG Capability Navigation]]
- [[LightRAG Project Navigation]]
- [[LightRAG GraphRAG Capability Knowledge Graph]]
- [[LightRAG GraphRAG Capability Development]]

## Open Questions

- Should future traces become durable if Agents start running multi-step production tasks?
