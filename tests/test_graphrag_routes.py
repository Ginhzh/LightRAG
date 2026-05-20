from fastapi import FastAPI
from fastapi.testclient import TestClient

from lightrag.api.routers.graphrag_routes import create_graphrag_routes
from tests.test_graphrag_capability import FakeRAG


def create_client():
    app = FastAPI()
    app.include_router(create_graphrag_routes(FakeRAG(), auth_dependency=lambda: None))
    return TestClient(app)


def test_graphrag_retrieve_route():
    client = create_client()

    response = client.post("/graphrag/retrieve", json={"query": "关系是什么"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["trace"]["operation"] == "retrieve"
    assert body["data"]["data"]["entities"][0]["entity_name"] == "A"


def test_graphrag_tool_route():
    client = create_client()

    response = client.post(
        "/graphrag/tools/search-entities",
        json={"query": "A", "top_k": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["entities"][0]["entity_name"] == "A"


def test_graphrag_plan_and_trace_routes():
    client = create_client()

    plan_response = client.post("/graphrag/plan", json={"query": "怎么查"})
    request_id = plan_response.json()["request_id"]
    trace_response = client.get(f"/graphrag/trace/{request_id}")

    assert plan_response.status_code == 200
    assert trace_response.status_code == 200
    assert trace_response.json()["status"] == "success"


def test_graphrag_tool_schemas_route():
    client = create_client()

    response = client.get("/graphrag/tool-schemas")

    assert response.status_code == 200
    assert response.json()["tools"][0]["schema_version"] == "2020-12"


def test_graphrag_ask_route_ignores_stream_option():
    client = create_client()

    response = client.post(
        "/graphrag/ask",
        json={"query": "回答", "options": {"stream": True}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["llm_response"]["response_iterator"] is None
