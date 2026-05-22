from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

from lightrag import LightRAG
from lightrag.base import QueryParam
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a LightRAG baseline query.")
    parser.add_argument("--question", required=True)
    parser.add_argument("--mode", required=True)
    return parser


async def llm_model_func(
    prompt,
    system_prompt=None,
    history_messages=None,
    keyword_extraction=False,
    **kwargs,
) -> str:
    keyword_extraction = False
    return await openai_complete_if_cache(
        os.getenv("LLM_MODEL", "deepseek-chat"),
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        keyword_extraction=keyword_extraction,
        api_key=os.getenv("LLM_BINDING_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("LLM_BINDING_HOST", "https://api.deepseek.com"),
        stream=kwargs.pop("stream", False),
        timeout=int(os.getenv("LLM_TIMEOUT", "180")),
        **kwargs,
    )


@asynccontextmanager
async def create_rag():
    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env", override=False)

    working_dir = os.getenv("LIGHTRAG_MCP_WORKING_DIR") or str(root / "data" / "rag_storage")
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "2560"))
    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_model_func,
        llm_model_name=os.getenv("LLM_MODEL", "deepseek-chat"),
        embedding_func=EmbeddingFunc(
            embedding_dim=embedding_dim,
            max_token_size=int(os.getenv("MAX_EMBED_TOKENS", "8192")),
            send_dimensions=os.getenv("EMBEDDING_SEND_DIM", "false").lower()
            in {"true", "1", "yes"},
            model_name=os.getenv("EMBEDDING_MODEL"),
            supports_asymmetric=True,
            func=partial(
                openai_embed.func,
                model=os.getenv("EMBEDDING_MODEL"),
                base_url=os.getenv("EMBEDDING_BINDING_HOST"),
                api_key=os.getenv("EMBEDDING_BINDING_API_KEY"),
            ),
        ),
        kv_storage=os.getenv("LIGHTRAG_KV_STORAGE", "JsonKVStorage"),
        vector_storage=os.getenv("LIGHTRAG_VECTOR_STORAGE", "NanoVectorDBStorage"),
        graph_storage=os.getenv("LIGHTRAG_GRAPH_STORAGE", "NetworkXStorage"),
        doc_status_storage=os.getenv(
            "LIGHTRAG_DOC_STATUS_STORAGE", "JsonDocStatusStorage"
        ),
        enable_llm_cache=False,
    )
    await rag.initialize_storages()
    try:
        yield rag
    finally:
        await rag.finalize_storages()


async def main_async(question: str, mode: str) -> None:
    async with create_rag() as rag:
        result = await rag.aquery_llm(question, param=QueryParam(mode=mode, stream=False))
        print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(main_async(args.question, args.mode))


if __name__ == "__main__":
    main()
