import asyncio
from pathlib import Path

import pytest

from lightrag.capabilities.graph_rag import (
    GraphRAGCapability,
    RetrievalBudget,
    TraceRecorder,
)


class FakeVectorStorage:
    def __init__(self, key):
        self.key = key
        self.calls = []

    async def query(self, query, top_k, query_embedding=None):
        self.calls.append({"query": query, "top_k": top_k})
        return [{self.key: query, "score": 0.9, "id": f"{self.key}-1"}]


class FakeGraphStorage:
    async def get_node_edges(self, source_node_id):
        if source_node_id == "A":
            return [("A", "B"), ("A", "C")]
        if source_node_id == "B":
            return [("B", "D")]
        return []

    async def get_edge(self, source_node_id, target_node_id):
        return {"description": f"{source_node_id}->{target_node_id}", "weight": 1.0}

    async def get_node(self, node_id):
        return {"entity_name": node_id, "description": f"Node {node_id}"}


class FakeRAG:
    def __init__(self):
        self.aquery_data_calls = []
        self.aquery_llm_calls = []
        self.entities_vdb = FakeVectorStorage("entity_name")
        self.relationships_vdb = FakeVectorStorage("src_id")
        self.chunks_vdb = FakeVectorStorage("chunk_id")
        self.chunk_entity_relation_graph = FakeGraphStorage()

    async def aquery_data(self, query, param):
        self.aquery_data_calls.append({"query": query, "param": param})
        return {
            "status": "success",
            "message": "ok",
            "data": {
                "entities": [{"entity_name": "A"}],
                "relationships": [{"src_id": "A", "tgt_id": "B"}],
                "chunks": [{"chunk_id": "c1", "content": "chunk"}],
                "references": [{"reference_id": "1", "file_path": "doc.md"}],
            },
            "metadata": {"query_mode": param.mode},
        }

    async def aquery_llm(self, query, param):
        self.aquery_llm_calls.append({"query": query, "param": param})
        return {
            "status": "success",
            "data": {"references": [{"reference_id": "1", "file_path": "doc.md"}]},
            "metadata": {"query_mode": param.mode},
            "llm_response": {
                "content": "answer",
                "response_iterator": None,
                "is_streaming": False,
            },
        }


def test_budget_enforces_hard_limits():
    assert RetrievalBudget().max_steps == 10
    assert RetrievalBudget().max_depth == 2

    with pytest.raises(ValueError):
        RetrievalBudget(max_steps=13)
    with pytest.raises(ValueError):
        RetrievalBudget(max_depth=3)
    with pytest.raises(ValueError):
        RetrievalBudget(timeout_seconds=61)


def test_retrieve_wraps_aquery_data_with_trace():
    asyncio.run(_test_retrieve_wraps_aquery_data_with_trace())


async def _test_retrieve_wraps_aquery_data_with_trace():
    rag = FakeRAG()
    capability = GraphRAGCapability(rag)

    result = await capability.retrieve("关系是什么", {"mode": "mix"})

    assert result["status"] == "success"
    assert rag.aquery_data_calls[0]["param"].mode == "mix"
    assert rag.aquery_data_calls[0]["param"].only_need_context is True
    assert result["trace"]["operation"] == "retrieve"
    assert result["metadata"]["evidence"]["status"] == "sufficient"


def test_ask_forces_non_streaming():
    asyncio.run(_test_ask_forces_non_streaming())


async def _test_ask_forces_non_streaming():
    rag = FakeRAG()
    capability = GraphRAGCapability(rag)

    result = await capability.ask("回答问题", {"mode": "mix"})

    assert result["status"] == "success"
    assert rag.aquery_llm_calls[0]["param"].stream is False
    assert result["data"]["llm_response"]["response_iterator"] is None


def test_plan_is_deterministic_and_does_not_call_rag():
    rag = FakeRAG()
    capability = GraphRAGCapability(rag)

    result = capability.plan("如何检索")

    assert result["status"] == "success"
    assert result["data"]["steps"][0]["step"] == "retrieve_context"
    assert rag.aquery_data_calls == []
    assert rag.aquery_llm_calls == []
    assert capability.trace(result["request_id"])["status"] == "success"
    assert capability.trace("missing")["status"] == "failure"


def test_trace_recorder_prunes_by_ttl_and_capacity():
    recorder = TraceRecorder(max_entries=2, ttl_seconds=3600)
    first = recorder.start(
        operation="one", query="q1", budget=RetrievalBudget()
    )
    second = recorder.start(
        operation="two", query="q2", budget=RetrievalBudget()
    )
    third = recorder.start(
        operation="three", query="q3", budget=RetrievalBudget()
    )

    assert recorder.get(first["request_id"]) is None
    assert recorder.get(second["request_id"]) is not None
    assert recorder.get(third["request_id"]) is not None

    expiring = TraceRecorder(max_entries=10, ttl_seconds=0)
    expired = expiring.start(
        operation="old", query="q", budget=RetrievalBudget()
    )
    assert expiring.get(expired["request_id"]) is None


def test_toolbox_vector_searches_and_limits():
    asyncio.run(_test_toolbox_vector_searches_and_limits())


async def _test_toolbox_vector_searches_and_limits():
    rag = FakeRAG()
    capability = GraphRAGCapability(rag)

    entities = await capability.search_entities("A", top_k=5)
    relationships = await capability.search_relationships("A to B", top_k=5)
    chunks = await capability.search_chunks("chunk", top_k=5)
    too_large = await capability.search_chunks("chunk", top_k=51)

    assert entities["data"]["entities"][0]["entity_name"] == "A"
    assert relationships["data"]["relationships"][0]["src_id"] == "A to B"
    assert chunks["data"]["chunks"][0]["chunk_id"] == "chunk"
    assert too_large["status"] == "failure"
    assert too_large["trace"]["stop_reason"] == "invalid_request"


def test_expand_neighbors_enforces_depth_and_returns_graph_data():
    asyncio.run(_test_expand_neighbors_enforces_depth_and_returns_graph_data())


async def _test_expand_neighbors_enforces_depth_and_returns_graph_data():
    rag = FakeRAG()
    capability = GraphRAGCapability(rag)

    result = await capability.expand_neighbors("A", depth=2)
    invalid = await capability.expand_neighbors("A", depth=3)
    invalid_limit = await capability.expand_neighbors("A", depth=1, limit=101)

    assert result["status"] == "success"
    assert "A" in result["data"]["nodes"]
    assert "B" in result["data"]["nodes"]
    assert result["data"]["relationships"][0]["src_id"] == "A"
    assert invalid["status"] == "failure"
    assert invalid_limit["status"] == "failure"


def test_tool_schemas_are_json_schema_metadata():
    capability = GraphRAGCapability(FakeRAG())
    schemas = capability.tool_schemas()

    assert {schema["name"] for schema in schemas} == {
        "graphrag_search_entities",
        "graphrag_search_relationships",
        "graphrag_search_chunks",
        "graphrag_expand_neighbors",
        "graphrag_retrieve_context",
    }
    assert all(schema["schema_version"] == "2020-12" for schema in schemas)
    for schema in schemas:
        input_schema = schema["input_schema"]
        assert input_schema["type"] == "object"
        assert "properties" in input_schema
        assert "required" in input_schema
    expand_schema = next(
        schema for schema in schemas if schema["name"] == "graphrag_expand_neighbors"
    )
    assert expand_schema["input_schema"]["properties"]["depth"]["maximum"] == 2
    entity_schema = next(
        schema for schema in schemas if schema["name"] == "graphrag_search_entities"
    )
    assert entity_schema["input_schema"]["properties"]["top_k"]["maximum"] == 50


def test_static_storage_access_boundaries():
    routes = Path("lightrag/api/routers/graphrag_routes.py").read_text()
    capability = Path("lightrag/capabilities/graph_rag.py").read_text()

    forbidden_route_refs = [
        "entities_vdb",
        "relationships_vdb",
        "chunks_vdb",
        "chunk_entity_relation_graph",
    ]
    assert all(ref not in routes for ref in forbidden_route_refs)
    assert ".upsert" not in capability
    assert ".delete" not in capability
    assert "_perform_kg_search" not in capability
