"""GraphRAG capability routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from lightrag.capabilities import GraphRAGCapability


class GraphRAGOptionsRequest(BaseModel):
    mode: Optional[str] = Field(default=None, description="LightRAG query mode")
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    chunk_top_k: Optional[int] = Field(default=None, ge=1, le=50)
    response_type: Optional[str] = None
    user_prompt: Optional[str] = None
    include_trace: bool = True
    enable_rerank: Optional[bool] = None
    stream: Optional[bool] = Field(
        default=None,
        description="Ignored in the first GraphRAG ask version; ask is non-streaming.",
    )
    budget: Optional[dict[str, Any]] = None


class GraphRAGQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    options: Optional[GraphRAGOptionsRequest] = None


class GraphRAGToolQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=50)


class GraphRAGExpandNeighborsRequest(BaseModel):
    entity_id: str = Field(min_length=1)
    depth: int = Field(default=1, ge=0, le=2)
    limit: Optional[int] = Field(default=None, ge=1, le=100)


def create_graphrag_routes(rag, api_key: Optional[str] = None, auth_dependency=None):
    router = APIRouter(prefix="/graphrag", tags=["graphrag"])
    if auth_dependency is None:
        from lightrag.api.utils_api import get_combined_auth_dependency

        auth_dependency = get_combined_auth_dependency(api_key)
    capability = GraphRAGCapability(rag)

    def options_to_dict(options: GraphRAGOptionsRequest | None) -> dict[str, Any]:
        if options is None:
            return {}
        data = options.model_dump(exclude_none=True)
        data.pop("stream", None)
        return data

    @router.post("/ask", dependencies=[Depends(auth_dependency)])
    async def ask(request: GraphRAGQueryRequest):
        return await capability.ask(request.query, options_to_dict(request.options))

    @router.post("/retrieve", dependencies=[Depends(auth_dependency)])
    async def retrieve(request: GraphRAGQueryRequest):
        return await capability.retrieve(request.query, options_to_dict(request.options))

    @router.post("/plan", dependencies=[Depends(auth_dependency)])
    async def plan(request: GraphRAGQueryRequest):
        return capability.plan(request.query, options_to_dict(request.options))

    @router.get("/trace/{request_id}", dependencies=[Depends(auth_dependency)])
    async def trace(request_id: str):
        return capability.trace(request_id)

    @router.get("/tool-schemas", dependencies=[Depends(auth_dependency)])
    async def tool_schemas():
        return {"status": "success", "tools": capability.tool_schemas()}

    @router.post("/tools/search-entities", dependencies=[Depends(auth_dependency)])
    async def search_entities(request: GraphRAGToolQueryRequest):
        return await capability.search_entities(request.query, request.top_k)

    @router.post("/tools/search-relationships", dependencies=[Depends(auth_dependency)])
    async def search_relationships(request: GraphRAGToolQueryRequest):
        return await capability.search_relationships(request.query, request.top_k)

    @router.post("/tools/search-chunks", dependencies=[Depends(auth_dependency)])
    async def search_chunks(request: GraphRAGToolQueryRequest):
        return await capability.search_chunks(request.query, request.top_k)

    @router.post("/tools/expand-neighbors", dependencies=[Depends(auth_dependency)])
    async def expand_neighbors(request: GraphRAGExpandNeighborsRequest):
        return await capability.expand_neighbors(
            request.entity_id, depth=request.depth, limit=request.limit
        )

    @router.post("/tools/retrieve-context", dependencies=[Depends(auth_dependency)])
    async def retrieve_context(request: GraphRAGQueryRequest):
        return await capability.retrieve_context(
            request.query, options_to_dict(request.options)
        )

    return router
