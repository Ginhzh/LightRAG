---
type: project-goals
status: active
created: 2026-05-20
updated: 2026-05-22
sources:
  - "[[2026-05-20-graphrag-capability-commit]]"
tags:
  - type/project
  - domain/lightrag
  - domain/mcp
provenance:
  extracted: 2
  inferred: 5
  ambiguous: 2
summary: "Near-term goals after the GraphRAG capability commit, focused on tool adapters and MCP wrapping."
---

# LightRAG Next Goals

## Summary

The next likely goal is to make the GraphRAG capability callable by LLM or Agent runtimes. The current code already exposes tool schema metadata, but it does not yet provide an MCP runtime server. ^[inferred]

## Target Goals

- Build a `GraphRAGToolAdapter` that maps tool names and arguments to [[GraphRAG Capability Layer]] methods. ^[inferred]
- Support direct LLM tool-calling before or alongside MCP server work. ^[inferred]
- Add an [[MCP Adapter Goal]] implementation only as a thin wrapper over the capability layer. ^[inferred]
- Keep retrieval logic inside [[GraphRAG Capability Layer]], not in REST, MCP, or future A2A layers. ^[extracted]
- Use [[Retrieval Harness Strategy]] to compare bounded GraphRAG retrieval against baseline modes before claiming quality improvements. ^[inferred]
- Keep [[External Knowledge Base Sync]] explicit and reviewable because it may move memory or conversation data outside the local repo. ^[inferred]

## Non-Goals Preserved

- Do not rewrite storage adapters. ^[extracted]
- Do not move graph-building or indexing logic. ^[extracted]
- Do not implement full A2A before the capability/tooling surface stabilizes. ^[inferred]

## Candidate Next Work Breakdown

1. Add tool adapter:
   - `list_tools()`
   - `call_tool(name, arguments)`
   - `to_openai_tools()`
   - `to_mcp_tools()` ^[inferred]
2. Add tests for argument validation and tool dispatch. ^[inferred]
3. Add MCP server wrapper if a target MCP runtime is selected. ^[ambiguous]

## Sources

- [[2026-05-20-graphrag-capability-commit]]

## Related Notes

- [[index|LightRAG LLM Wiki Index]]
- [[LightRAG Capability Navigation]]
- [[LightRAG Project Navigation]]
- [[GraphRAG Capability Layer]]
- [[MCP Adapter Goal]]
- [[Agent Tooling Surface]]
- [[Bounded Agent Autonomy]]
- [[LightRAG GraphRAG Capability Development]]
- [[LightRAG GraphRAG Capability Knowledge Graph]]
- [[Retrieval Harness Strategy]]
- [[External Knowledge Base Sync]]

## Open Questions

- Which MCP Python SDK or server runtime should be used? ^[ambiguous]
- Should direct tool calling be implemented before MCP server integration?
