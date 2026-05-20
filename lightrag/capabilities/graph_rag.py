"""GraphRAG capability facade for application and Agent callers."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from lightrag.base import QueryParam


GraphRAGStatus = Literal["success", "failure"]
MAX_STEPS_LIMIT = 12
MAX_DEPTH_LIMIT = 2
MAX_VECTOR_TOP_K = 50
MAX_EXPAND_LIMIT = 100
MAX_ENTITIES_LIMIT = 50
MAX_RELATIONSHIPS_LIMIT = 100
MAX_CHUNKS_LIMIT = 50
MAX_TIMEOUT_SECONDS = 60


@dataclass(slots=True)
class RetrievalBudget:
    """Bounded autonomy defaults for Agent graph exploration."""

    max_steps: int = 10
    max_depth: int = 2
    max_entities: int = 20
    max_relationships: int = 30
    max_chunks: int = 20
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        self._validate_range("max_steps", self.max_steps, 1, MAX_STEPS_LIMIT)
        self._validate_range("max_depth", self.max_depth, 0, MAX_DEPTH_LIMIT)
        self._validate_range("max_entities", self.max_entities, 1, MAX_ENTITIES_LIMIT)
        self._validate_range(
            "max_relationships", self.max_relationships, 1, MAX_RELATIONSHIPS_LIMIT
        )
        self._validate_range("max_chunks", self.max_chunks, 1, MAX_CHUNKS_LIMIT)
        self._validate_range(
            "timeout_seconds", self.timeout_seconds, 1, MAX_TIMEOUT_SECONDS
        )

    def _validate_range(self, name: str, value: int, minimum: int, maximum: int) -> None:
        if value < minimum or value > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class GraphRAGOptions:
    """Options shared by high-level GraphRAG capability methods."""

    mode: Literal["local", "global", "hybrid", "naive", "mix", "bypass"] = "mix"
    top_k: int | None = None
    chunk_top_k: int | None = None
    response_type: str | None = None
    user_prompt: str | None = None
    include_trace: bool = True
    enable_rerank: bool | None = None
    budget: RetrievalBudget = field(default_factory=RetrievalBudget)

    @classmethod
    def from_mapping(cls, options: dict[str, Any] | None) -> "GraphRAGOptions":
        if not options:
            return cls()

        option_data = dict(options)
        option_data.pop("stream", None)
        budget_data = option_data.pop("budget", None)
        if isinstance(budget_data, RetrievalBudget):
            budget = budget_data
        elif isinstance(budget_data, dict):
            budget = RetrievalBudget(**budget_data)
        elif budget_data is None:
            budget = RetrievalBudget()
        else:
            raise ValueError("budget must be a mapping or RetrievalBudget")

        return cls(**option_data, budget=budget)

    def to_query_param(self, *, stream: bool = False, only_need_context: bool = False) -> QueryParam:
        param_data: dict[str, Any] = {
            "mode": self.mode,
            "stream": stream,
            "only_need_context": only_need_context,
        }
        if self.top_k is not None:
            param_data["top_k"] = self.top_k
        if self.chunk_top_k is not None:
            param_data["chunk_top_k"] = self.chunk_top_k
        if self.response_type is not None:
            param_data["response_type"] = self.response_type
        if self.user_prompt is not None:
            param_data["user_prompt"] = self.user_prompt
        if self.enable_rerank is not None:
            param_data["enable_rerank"] = self.enable_rerank
        return QueryParam(**param_data)


class TraceRecorder:
    """Small in-memory trace store for capability calls."""

    def __init__(self, *, max_entries: int = 200, ttl_seconds: int = 3600) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._traces: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def start(
        self,
        *,
        operation: str,
        query: str | None,
        budget: RetrievalBudget,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        trace = {
            "request_id": request_id,
            "operation": operation,
            "query": query,
            "started_at": time.time(),
            "finished_at": None,
            "budget": budget.to_dict(),
            "inputs": inputs or {},
            "tool_calls": [],
            "result_counts": {},
            "stop_reason": None,
            "warnings": [],
            "errors": [],
        }
        self._prune()
        self._traces[request_id] = trace
        self._traces.move_to_end(request_id)
        self._prune()
        return trace

    def record_call(
        self,
        trace: dict[str, Any],
        *,
        tool: str,
        inputs: dict[str, Any],
        result_count: int | None = None,
    ) -> None:
        call = {"tool": tool, "inputs": inputs}
        if result_count is not None:
            call["result_count"] = result_count
        trace["tool_calls"].append(call)

    def finish(
        self,
        trace: dict[str, Any],
        *,
        stop_reason: str,
        result_counts: dict[str, int] | None = None,
        warning: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        trace["finished_at"] = time.time()
        trace["stop_reason"] = stop_reason
        if result_counts:
            trace["result_counts"] = result_counts
        if warning:
            trace["warnings"].append(warning)
        if error:
            trace["errors"].append(error)
        return trace

    def get(self, request_id: str) -> dict[str, Any] | None:
        self._prune()
        trace = self._traces.get(request_id)
        if trace is not None:
            self._traces.move_to_end(request_id)
        return trace

    def _prune(self) -> None:
        now = time.time()
        expired = [
            request_id
            for request_id, trace in self._traces.items()
            if now - trace["started_at"] > self.ttl_seconds
        ]
        for request_id in expired:
            self._traces.pop(request_id, None)
        while len(self._traces) > self.max_entries:
            self._traces.popitem(last=False)


class EvidenceEvaluator:
    """Lightweight evidence sufficiency scoring without model training."""

    def evaluate(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = data.get("data", data) if isinstance(data, dict) else {}
        entities = payload.get("entities", []) or []
        relationships = payload.get("relationships", []) or []
        chunks = payload.get("chunks", []) or []
        references = payload.get("references", []) or []

        reasons: list[str] = []
        gaps: list[str] = []
        score = 0.0
        if entities:
            score += 0.25
            reasons.append("matched_entities")
        else:
            gaps.append("no_entities")
        if relationships:
            score += 0.25
            reasons.append("matched_relationships")
        else:
            gaps.append("no_relationships")
        if chunks:
            score += 0.30
            reasons.append("supporting_chunks")
        else:
            gaps.append("no_chunks")
        if references:
            score += 0.20
            reasons.append("references_available")
        else:
            gaps.append("no_references")

        if score >= 0.70:
            status = "sufficient"
        elif score > 0:
            status = "partial"
        else:
            status = "empty"

        return {
            "score": round(score, 2),
            "status": status,
            "reasons": reasons,
            "gaps": gaps,
        }


class GraphRAGCapability:
    """Thin GraphRAG facade around an existing ``LightRAG`` instance."""

    def __init__(self, rag: Any):
        self.rag = rag
        self._traces = TraceRecorder()
        self._evaluator = EvidenceEvaluator()

    async def ask(
        self, query: str, options: dict[str, Any] | GraphRAGOptions | None = None
    ) -> dict[str, Any]:
        opts = self._coerce_options(options)
        trace = self._traces.start(operation="ask", query=query, budget=opts.budget)
        param = opts.to_query_param(stream=False)
        self._traces.record_call(trace, tool="aquery_llm", inputs={"mode": param.mode})

        try:
            result = await asyncio.wait_for(
                self.rag.aquery_llm(query, param=param),
                timeout=opts.budget.timeout_seconds,
            )
            raw_data = result.get("data", {}) if isinstance(result, dict) else {}
            references = raw_data.get("references", []) if isinstance(raw_data, dict) else []
            self._traces.finish(
                trace,
                stop_reason="completed",
                result_counts={"references": len(references)},
            )
            return self._result(
                "success",
                trace,
                query=query,
                data=result,
                metadata={"evidence": self._evaluator.evaluate(result)},
            )
        except Exception as exc:
            self._traces.finish(trace, stop_reason="error", error=str(exc))
            return self._result("failure", trace, query=query, data={}, message=str(exc))

    async def retrieve(
        self, query: str, options: dict[str, Any] | GraphRAGOptions | None = None
    ) -> dict[str, Any]:
        opts = self._coerce_options(options)
        trace = self._traces.start(operation="retrieve", query=query, budget=opts.budget)
        param = opts.to_query_param(stream=False, only_need_context=True)
        self._traces.record_call(trace, tool="aquery_data", inputs={"mode": param.mode})

        try:
            result = await asyncio.wait_for(
                self.rag.aquery_data(query, param=param),
                timeout=opts.budget.timeout_seconds,
            )
            counts = self._count_data(result)
            self._traces.finish(trace, stop_reason="completed", result_counts=counts)
            return self._result(
                "success",
                trace,
                query=query,
                data=result,
                metadata={"evidence": self._evaluator.evaluate(result)},
            )
        except Exception as exc:
            self._traces.finish(trace, stop_reason="error", error=str(exc))
            return self._result("failure", trace, query=query, data={}, message=str(exc))

    def plan(
        self, query: str, options: dict[str, Any] | GraphRAGOptions | None = None
    ) -> dict[str, Any]:
        opts = self._coerce_options(options)
        trace = self._traces.start(operation="plan", query=query, budget=opts.budget)
        plan_steps = [
            {
                "step": "retrieve_context",
                "purpose": "Collect graph entities, relationships, chunks, and references.",
            },
            {
                "step": "evaluate_evidence",
                "purpose": "Check whether retrieved evidence is sufficient.",
            },
        ]
        self._traces.finish(
            trace,
            stop_reason="planned",
            result_counts={"planned_steps": len(plan_steps)},
        )
        return self._result(
            "success",
            trace,
            query=query,
            data={"steps": plan_steps},
            metadata={"budget": opts.budget.to_dict()},
        )

    def trace(self, request_id: str) -> dict[str, Any]:
        trace = self._traces.get(request_id)
        if trace is None:
            return {"status": "failure", "message": "Trace not found", "request_id": request_id}
        return {"status": "success", "request_id": request_id, "trace": trace}

    async def search_entities(
        self, query: str, top_k: int | None = None, budget: RetrievalBudget | None = None
    ) -> dict[str, Any]:
        budget = budget or RetrievalBudget()
        trace = self._traces.start(operation="search_entities", query=query, budget=budget)
        storage = getattr(self.rag, "entities_vdb", None)
        if storage is None:
            return self._missing_storage(trace, query, "entities_vdb")

        try:
            limit = self._bounded_top_k(top_k, budget.max_entities)
        except ValueError as exc:
            self._traces.finish(trace, stop_reason="invalid_request", error=str(exc))
            return self._result("failure", trace, query=query, data={}, message=str(exc))
        return await self._vector_search(trace, query, storage, "entities", limit)

    async def search_relationships(
        self, query: str, top_k: int | None = None, budget: RetrievalBudget | None = None
    ) -> dict[str, Any]:
        budget = budget or RetrievalBudget()
        trace = self._traces.start(operation="search_relationships", query=query, budget=budget)
        storage = getattr(self.rag, "relationships_vdb", None)
        if storage is None:
            return self._missing_storage(trace, query, "relationships_vdb")

        try:
            limit = self._bounded_top_k(top_k, budget.max_relationships)
        except ValueError as exc:
            self._traces.finish(trace, stop_reason="invalid_request", error=str(exc))
            return self._result("failure", trace, query=query, data={}, message=str(exc))
        return await self._vector_search(trace, query, storage, "relationships", limit)

    async def search_chunks(
        self, query: str, top_k: int | None = None, budget: RetrievalBudget | None = None
    ) -> dict[str, Any]:
        budget = budget or RetrievalBudget()
        trace = self._traces.start(operation="search_chunks", query=query, budget=budget)
        storage = getattr(self.rag, "chunks_vdb", None)
        if storage is None:
            return self._missing_storage(trace, query, "chunks_vdb")

        try:
            limit = self._bounded_top_k(top_k, budget.max_chunks)
        except ValueError as exc:
            self._traces.finish(trace, stop_reason="invalid_request", error=str(exc))
            return self._result("failure", trace, query=query, data={}, message=str(exc))
        return await self._vector_search(trace, query, storage, "chunks", limit)

    async def expand_neighbors(
        self,
        entity_id: str,
        depth: int = 1,
        limit: int | None = None,
        budget: RetrievalBudget | None = None,
    ) -> dict[str, Any]:
        budget = budget or RetrievalBudget()
        trace = self._traces.start(
            operation="expand_neighbors",
            query=None,
            budget=budget,
            inputs={"entity_id": entity_id, "depth": depth},
        )
        if depth > budget.max_depth:
            message = "depth exceeds max_depth=2"
            self._traces.finish(trace, stop_reason="invalid_request", error=message)
            return self._result("failure", trace, data={}, message=message)
        if limit is not None and (limit < 1 or limit > MAX_EXPAND_LIMIT):
            message = f"limit must be between 1 and {MAX_EXPAND_LIMIT}"
            self._traces.finish(trace, stop_reason="invalid_request", error=message)
            return self._result("failure", trace, data={}, message=message)

        graph = getattr(self.rag, "chunk_entity_relation_graph", None)
        if graph is None:
            return self._missing_storage(trace, None, "chunk_entity_relation_graph")

        max_items = min(limit or budget.max_relationships, budget.max_relationships)
        nodes: dict[str, dict[str, Any]] = {}
        relationships: list[dict[str, Any]] = []
        frontier = [entity_id]
        visited = {entity_id}

        try:
            for current_depth in range(depth):
                next_frontier: list[str] = []
                for node_id in frontier:
                    edges = await asyncio.wait_for(
                        graph.get_node_edges(node_id),
                        timeout=budget.timeout_seconds,
                    ) or []
                    self._traces.record_call(
                        trace,
                        tool="get_node_edges",
                        inputs={"entity_id": node_id, "depth": current_depth + 1},
                        result_count=len(edges),
                    )
                    for src_id, tgt_id in edges:
                        if len(relationships) >= max_items:
                            break
                        edge_data = await asyncio.wait_for(
                            graph.get_edge(src_id, tgt_id),
                            timeout=budget.timeout_seconds,
                        )
                        relationships.append(
                            {
                                "src_id": src_id,
                                "tgt_id": tgt_id,
                                "data": edge_data or {},
                                "depth": current_depth + 1,
                            }
                        )
                        for neighbor in (src_id, tgt_id):
                            if neighbor not in visited:
                                visited.add(neighbor)
                                next_frontier.append(neighbor)
                    if len(relationships) >= max_items:
                        break
                frontier = next_frontier

            for node_id in visited:
                node_data = await asyncio.wait_for(
                    graph.get_node(node_id),
                    timeout=budget.timeout_seconds,
                )
                if node_data is not None:
                    nodes[node_id] = node_data

            data = {"nodes": nodes, "relationships": relationships}
            self._traces.finish(
                trace,
                stop_reason="completed",
                result_counts={"nodes": len(nodes), "relationships": len(relationships)},
            )
            return self._result("success", trace, data=data)
        except Exception as exc:
            self._traces.finish(trace, stop_reason="error", error=str(exc))
            return self._result("failure", trace, data={}, message=str(exc))

    async def retrieve_context(
        self, query: str, options: dict[str, Any] | GraphRAGOptions | None = None
    ) -> dict[str, Any]:
        return await self.retrieve(query, options)

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            self._tool_schema(
                "graphrag_search_entities",
                "Search graph entities by semantic query.",
                {
                    "query": {"type": "string", "minLength": 1},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                ["query"],
            ),
            self._tool_schema(
                "graphrag_search_relationships",
                "Search graph relationships by semantic query.",
                {
                    "query": {"type": "string", "minLength": 1},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                ["query"],
            ),
            self._tool_schema(
                "graphrag_search_chunks",
                "Search document chunks by semantic query.",
                {
                    "query": {"type": "string", "minLength": 1},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                ["query"],
            ),
            self._tool_schema(
                "graphrag_expand_neighbors",
                "Expand graph neighbors for an entity with max depth 2.",
                {
                    "entity_id": {"type": "string", "minLength": 1},
                    "depth": {"type": "integer", "minimum": 0, "maximum": 2},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                ["entity_id"],
            ),
            self._tool_schema(
                "graphrag_retrieve_context",
                "Retrieve GraphRAG evidence context using existing LightRAG retrieval.",
                {
                    "query": {"type": "string", "minLength": 1},
                    "options": {"type": "object"},
                },
                ["query"],
            ),
        ]

    async def _vector_search(
        self,
        trace: dict[str, Any],
        query: str,
        storage: Any,
        result_key: str,
        top_k: int,
    ) -> dict[str, Any]:
        try:
            self._traces.record_call(trace, tool=f"{result_key}_vdb.query", inputs={"top_k": top_k})
            timeout = trace["budget"]["timeout_seconds"]
            results = await asyncio.wait_for(
                storage.query(query, top_k=top_k), timeout=timeout
            )
            data = {result_key: results}
            self._traces.finish(
                trace,
                stop_reason="completed",
                result_counts={result_key: len(results)},
            )
            return self._result("success", trace, query=query, data=data)
        except Exception as exc:
            self._traces.finish(trace, stop_reason="error", error=str(exc))
            return self._result("failure", trace, query=query, data={}, message=str(exc))

    def _missing_storage(
        self, trace: dict[str, Any], query: str | None, storage_name: str
    ) -> dict[str, Any]:
        message = f"{storage_name} is not configured"
        self._traces.finish(trace, stop_reason="missing_storage", warning=message)
        return self._result("failure", trace, query=query, data={}, message=message)

    def _result(
        self,
        status: GraphRAGStatus,
        trace: dict[str, Any],
        *,
        query: str | None = None,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "message": message or ("GraphRAG capability call completed" if status == "success" else "GraphRAG capability call failed"),
            "request_id": trace["request_id"],
            "query": query,
            "data": data,
            "metadata": metadata or {},
            "trace": trace,
        }

    def _coerce_options(
        self, options: dict[str, Any] | GraphRAGOptions | None
    ) -> GraphRAGOptions:
        if isinstance(options, GraphRAGOptions):
            return options
        return GraphRAGOptions.from_mapping(options)

    def _count_data(self, result: dict[str, Any]) -> dict[str, int]:
        payload = result.get("data", {}) if isinstance(result, dict) else {}
        return {
            "entities": len(payload.get("entities", []) or []),
            "relationships": len(payload.get("relationships", []) or []),
            "chunks": len(payload.get("chunks", []) or []),
            "references": len(payload.get("references", []) or []),
        }

    def _tool_schema(
        self,
        name: str,
        description: str,
        properties: dict[str, dict[str, Any]],
        required: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": "2020-12",
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            "output": "Structured GraphRAG capability result with status, data, metadata, and trace.",
        }

    def _bounded_top_k(self, top_k: int | None, default_limit: int) -> int:
        if top_k is None:
            return min(default_limit, MAX_VECTOR_TOP_K)
        if top_k < 1 or top_k > MAX_VECTOR_TOP_K:
            raise ValueError(f"top_k must be between 1 and {MAX_VECTOR_TOP_K}")
        return min(top_k, default_limit, MAX_VECTOR_TOP_K)
