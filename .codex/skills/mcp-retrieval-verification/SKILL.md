---
name: mcp-retrieval-verification
description: Use when validating LightRAG GraphRAG MCP retrieval on this repository, especially when an agent should try entity, relationship, chunk, and context retrieval separately against a real knowledge base instead of sending full graph context to the model.
---

# MCP Retrieval Verification

## Overview

Use this skill to verify that LightRAG's MCP layer can support agent-driven, multi-index retrieval on a real knowledge base. The goal is to prove or disprove a specific behavior:

- the agent should call separate retrieval tools
- the system should search entity, relationship, and chunk indexes independently
- only then should it assemble context or ask the model

This skill is for verification and debugging, not feature design.

For harness strategy changes or post-evaluation tuning, also use
`$retrieval-harness-strategy`. That skill captures the round-3 lessons about
full related-hint relation probing, weak-link expansion, and answer-text output.

## When to Use

Use this skill when:

- MCP tools appear healthy in unit tests but real retrieval needs confirmation
- the user wants evidence that an agent can explore different indexes by itself
- retrieval fails and you need to separate MCP issues from embedding-service issues
- `search_entities`, `search_relationships`, `search_chunks`, or `retrieve_context` behave inconsistently between smoke data and the real `rag_storage`

Do not use this skill for generic LightRAG setup or unrelated MCP servers.

## What to Verify

For a successful verification, confirm all of the following:

1. MCP server starts from `examples.mcp_lightrag_env_factory:create_rag`
2. Real storages load from `data/rag_storage`
3. fine-grained tools return structured results:
   - `graphrag_search_entities`
   - `graphrag_search_relationships`
   - `graphrag_search_chunks`
4. composition tools return structured results:
   - `graphrag_retrieve_context`
   - `graphrag_plan`
   - `graphrag_trace`
   - optionally `graphrag_ask`
5. retrieval uses multiple indexes instead of only one high-level ask path
6. harness or baseline outputs include scoreable answer text, not only structured context

## Workflow

### 1. Check local configuration

- Read `.env`
- Confirm:
  - `EMBEDDING_BINDING_HOST`
  - `EMBEDDING_MODEL`
  - `LIGHTRAG_*_STORAGE`
- Confirm `data/rag_storage` exists and contains:
  - `vdb_entities.json`
  - `vdb_relationships.json`
  - `vdb_chunks.json`
  - `graph_chunk_entity_relation.graphml`

### 2. Confirm embedding service availability

If retrieval depends on the remote embedding server, verify the endpoint before blaming MCP.

For this repository's known setup, the remote service may be on:

- `http://10.12.222.108:8001/v1`

When remote startup is needed:

1. SSH to the remote host
2. Activate `qwen3-embed`
3. Start:

```bash
vllm serve ./data/models/Qwen3-Embedding-4B \
  --runner pooling \
  --convert embed \
  --trust-remote-code \
  --host 0.0.0.0 \
  --port 8001 \
  --dtype float16 \
  --gpu-memory-utilization 0.85
```

4. Verify:
   - process exists
   - port `8001` is listening
   - `GET /v1/models` succeeds

If the port is already in use, inspect before replacing an existing process.

## 3. Run baseline MCP tests

Run targeted MCP tests before blaming real data:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ./scripts/test.sh tests/test_graphrag_mcp.py
```

If a new serialization or capability bug is suspected, also run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ./scripts/test.sh tests/test_graphrag_capability.py
```

Use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` in this repository to avoid unrelated external pytest plugins interfering with verification.

## 4. Run real MCP retrieval checks

Use a real stdio MCP client against `examples.mcp_lightrag_env_factory:create_rag`.

Minimum tool sequence:

1. `list_tools`
2. `graphrag_search_entities`
3. `graphrag_search_relationships`
4. `graphrag_search_chunks`
5. `graphrag_retrieve_context`
6. `graphrag_plan`
7. `graphrag_trace`
8. optional `graphrag_ask`

Treat the retrieval as successful only if the fine-grained `search_*` tools and the composed `retrieve_context` call both return structured data.

For relation-heavy harness cases, verify the RelationExplorer does not stop at
`subject_hint + first related_hint`. It must probe every `related_hints` item and
then run bounded weak-link expansion from the subject, hints, and first-round
relationship endpoints.

## 5. Interpret failures correctly

### Embedding service failure

Symptoms:

- retries against `/embeddings`
- upstream `502`
- MCP server starts, but real retrieval stalls or fails

Interpretation:

- MCP routing may still be correct
- the failure is in the embedding dependency, not necessarily the retrieval design

### MCP serialization failure

Symptoms:

- fine-grained tools fail, but `retrieve_context` or `ask` may still work
- error mentions unsupported serialization such as `numpy.float32`

Interpretation:

- retrieval likely succeeded internally
- returned payload contains non-JSON-native scalar types
- normalize result payloads before MCP structured output

### Retrieval quality issue

Symptoms:

- tools return structured results, but hits are semantically weak

Interpretation:

- MCP transport is working
- the problem is ranking, embedding quality, query phrasing, or knowledge-base content

### Harness strategy issue

Symptoms:

- all MCP calls succeed, but multi-hint questions only cover a local strong edge
- baseline success output is structured context instead of a short answer
- `harness`, `naive`, and `mix` all show success, but answer quality is indistinguishable

Interpretation:

- transport is healthy
- improve harness query strategy and answer extraction before making quality claims

## Fix Pattern: Non-JSON Scalars

If real `search_*` results fail because of types such as `numpy.float32`, normalize returned payloads at the capability result boundary.

For this repository, a safe fix point is `lightrag/capabilities/graph_rag.py`, normalizing:

- `data`
- `metadata`
- `trace`

Use a recursive normalizer that converts values with `.item()` into native Python scalars.

Add a regression test first.

## Expected Evidence

Good evidence includes:

- `tests/test_graphrag_mcp.py` passing
- `list_tools` showing all GraphRAG tools
- logs showing entity, relationship, and chunk retrieval paths
- structured results from `search_entities`, `search_relationships`, `search_chunks`
- `retrieve_context` returning entities, relationships, chunks, and references

## Reporting Template

When reporting results, include:

1. embedding endpoint status
2. MCP test status
3. fine-grained retrieval status
4. composed retrieval status
5. root cause if anything failed
6. whether the repository currently supports agent-driven multi-index retrieval
7. whether relation exploration covered all related hints and weak links
8. whether harness and baseline answer text is scoreable

## Repository-Specific Notes

- Real storage path: `data/rag_storage`
- Real MCP factory: `examples.mcp_lightrag_env_factory:create_rag`
- Smoke factory: `examples.mcp_smoke_factory:create_rag`
- Fine-grained retrieval behavior lives in [lightrag/capabilities/graph_rag.py](/data/LightRAG/lightrag/capabilities/graph_rag.py)
- MCP wrapping lives in [lightrag/capabilities/mcp.py](/data/LightRAG/lightrag/capabilities/mcp.py)
