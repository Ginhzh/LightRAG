from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call a LightRAG MCP tool and return JSON.")
    parser.add_argument("--tool", required=True)
    parser.add_argument("--payload", required=True)
    return parser


def _payload_text(result):
    if result.structuredContent is not None:
        return result.structuredContent
    return [getattr(item, "text", str(item)) for item in result.content]


async def main_async(tool: str, payload: dict) -> None:
    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env", override=False)
    env = dict(os.environ)
    env.setdefault("LIGHTRAG_MCP_WORKING_DIR", str(root / "data" / "rag_storage"))

    params = StdioServerParameters(
        command="uv",
        args=[
            "run",
            "python",
            "-m",
            "lightrag.tools.mcp_server",
            "--factory",
            "examples.mcp_lightrag_env_factory:create_rag",
            "--transport",
            "stdio",
        ],
        cwd=root,
        env=env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool, payload)
            print(json.dumps(_payload_text(result), ensure_ascii=False))


def main() -> None:
    args = build_parser().parse_args()
    payload = json.loads(args.payload)
    asyncio.run(main_async(args.tool, payload))


if __name__ == "__main__":
    main()
