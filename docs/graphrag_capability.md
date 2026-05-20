# GraphRAG Capability Layer

LightRAG now exposes a thin GraphRAG capability layer for application code and
Agent/tool callers. The layer reuses existing LightRAG query behavior and adds
bounded, read-only graph/RAG tools.

## Python API

```python
from lightrag import GraphRAGCapability

capability = GraphRAGCapability(rag)

retrieval = await capability.retrieve("A 和 B 有什么关系？")
answer = await capability.ask("A 和 B 有什么关系？")
plan = capability.plan("A 和 B 有什么关系？")
trace = capability.trace(retrieval["request_id"])
```

## Agent Tools

```python
await capability.search_entities("A", top_k=5)
await capability.search_relationships("A B", top_k=5)
await capability.search_chunks("A B 关系", top_k=5)
await capability.expand_neighbors("A", depth=2)
await capability.retrieve_context("A 和 B 有什么关系？")
```

Default autonomy limits:

- `max_steps=10`
- `max_depth=2`
- `top_k <= 50`
- `expand_neighbors.limit <= 100`
- `timeout_seconds <= 60`

Unsafe limits are rejected rather than silently expanded.

## REST API

The API server registers a separate `/graphrag/*` route surface:

- `POST /graphrag/ask`
- `POST /graphrag/retrieve`
- `POST /graphrag/plan`
- `GET /graphrag/trace/{request_id}`
- `GET /graphrag/tool-schemas`
- `POST /graphrag/tools/search-entities`
- `POST /graphrag/tools/search-relationships`
- `POST /graphrag/tools/search-chunks`
- `POST /graphrag/tools/expand-neighbors`
- `POST /graphrag/tools/retrieve-context`

`/graphrag/ask` is non-streaming in the first version. Use existing `/query`
streaming routes for streaming responses.

## Trace Contract

Trace storage is in-process, best-effort, and not durable across process
restart or multi-worker boundaries. The default store keeps 200 entries for
3600 seconds.

## Tool Schema Metadata

`GraphRAGCapability.tool_schemas()` returns JSON Schema draft 2020-12
compatible metadata. It does not introduce an MCP runtime dependency.
