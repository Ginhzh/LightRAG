---
type: raw-source
status: processed
created: 2026-05-20
source_kind: git-commit-and-report
commit: bad00fd1d0c2c69b467b032dd53e539190174589
tags:
  - type/raw
  - domain/lightrag
---

# 2026-05-20 GraphRAG Capability Commit

Source commit:

```text
bad00fd1d0c2c69b467b032dd53e539190174589
Expose GraphRAG as a bounded reusable capability
AuthorDate: 2026-05-20 08:32:11 +0800
```

Commit narrative:

> The new capability layer lets application code and Agent/tool callers reuse LightRAG retrieval without changing indexing, storage, or existing query routes. It wraps aquery_data/aquery_llm for high-level calls and exposes read-only graph/RAG tools with hard autonomy limits and trace metadata.

Constraints recorded in the commit:

- Do not alter graph-building, storage adapters, or existing `/query` behavior.
- First version must support backend and LLM/tool callers without adding MCP or A2A runtime dependencies.

Rejected alternatives recorded in the commit:

- Full A2A Agent: out of first-pass scope and would couple protocol concerns to core retrieval.
- Storage rewrite: violates the low-intrusion requirement and user confidence boundary.

Tested:

```text
./scripts/test.sh tests/test_graphrag_capability.py tests/test_graphrag_routes.py
14 passed, 2 warnings
```

Not tested:

- `ruff check` was unavailable in the current environment.
- Full repository test suite was not run.

Files changed:

- `docs/graphrag_capability.md`
- `lightrag/__init__.py`
- `lightrag/api/lightrag_server.py`
- `lightrag/api/routers/__init__.py`
- `lightrag/api/routers/graphrag_routes.py`
- `lightrag/capabilities/__init__.py`
- `lightrag/capabilities/graph_rag.py`
- `tests/test_graphrag_capability.py`
- `tests/test_graphrag_routes.py`
