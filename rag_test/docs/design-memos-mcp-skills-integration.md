# MemOS 持久化记忆集成 Claude Code / Codex — 设计文档

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                   Claude Code / Codex                    │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ memory-search│  │ memory-store │  │ memory-sync  │  │
│  │   (Skill)    │  │   (Skill)    │  │   (Skill)    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │           │
│  ┌──────┴─────────────────┴─────────────────┴───────┐  │
│  │              MCP Server (远程模式)                 │  │
│  │         mcp_serve_remote.py via SSE/HTTP          │  │
│  │  Tools: search_memory · add_memory · get_memory   │  │
│  │         add_message · delete_memory · chat         │  │
│  └──────────────────────┬───────────────────────────┘  │
└─────────────────────────┼───────────────────────────────┘
                          │ HTTP (MemOSClient)
                          ▼
              ┌───────────────────────┐
              │   MemOS Product API   │
              │   /product/search     │
              │   /product/add        │
              │   /product/chat       │
              │   /api/openmem/v1/*   │
              └───────────────────────┘
```

两层模型：

- **能力层 — MCP Server (`mcp_serve_remote.py`)**：封装 `MemOSClient` HTTP 客户端，将 MemOS API 暴露为 MCP Tools。与现有 `mcp_serve.py`（本地模式，直接实例化 MOS 内核）互补，远程模式无需本地 Neo4j/Qdrant 等依赖。
- **策略层 — Skills**：面向用户意图的高层指令。每个 Skill 是一段 prompt 模板，告诉模型何时、如何调用 MCP Tools，并规定输出格式。

## 2. 远程模式 MCP Server — `src/memos/api/mcp_serve_remote.py`

### 2.1 职责

通过 `MemOSClient` 调用远程 MemOS Product API / OpenMem API，将其包装为 MCP Tools，供 Claude Code 通过 SSE/HTTP 传输协议调用。

### 2.2 实现规格

```python
#!/usr/bin/env python3
"""
Remote-mode MCP Server for MemOS.

Unlike mcp_serve.py (local mode, requires Neo4j/Qdrant), this server
delegates all operations to a remote MemOS instance via MemOSClient HTTP calls.

Usage:
  # SSE (recommended for Claude Code)
  python -m memos.api.mcp_serve_remote --transport sse --port 8100

  # stdio (for local pipe)
  python -m memos.api.mcp_serve_remote --transport stdio
"""
from __future__ import annotations

import argparse
import os
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from memos.api.client import MemOSClient

load_dotenv()


def _build_client() -> MemOSClient:
    return MemOSClient(
        api_key=os.getenv("MEMOS_API_KEY"),
        base_url=os.getenv("MEMOS_BASE_URL"),
        is_global=os.getenv("MEMOS_IS_GLOBAL", "false"),
    )


def _default_user_id() -> str:
    return os.getenv("MEMOS_DEFAULT_USER_ID", "")


def _default_conversation_id() -> str:
    return os.getenv("MEMOS_DEFAULT_CONVERSATION_ID", "claude-code")


class RemoteMCPServer:
    """MCP Server backed by MemOSClient (remote HTTP)."""

    def __init__(self):
        self.mcp = FastMCP("MemOS Remote Memory")
        self.client = _build_client()
        self._setup_tools()

    # ── Tools ────────────────────────────────────────────

    def _setup_tools(self):

        @self.mcp.tool()
        async def search_memory(
            query: str,
            user_id: str | None = None,
            conversation_id: str | None = None,
            top_k: int = 6,
            include_preference: bool = True,
        ) -> dict[str, Any]:
            """
            Search the user's persistent memories by semantic query.

            Returns matching memories ranked by relevance, including
            factual memories and (optionally) preference memories.
            """
            uid = user_id or _default_user_id()
            cid = conversation_id or _default_conversation_id()
            if not uid:
                return {"error": "user_id is required (set MEMOS_DEFAULT_USER_ID)"}
            resp = self.client.search_memory(
                query=query,
                user_id=uid,
                conversation_id=cid,
                memory_limit_number=top_k,
                include_preference=include_preference,
            )
            if resp is None:
                return {"error": "search returned None"}
            return resp.model_dump()

        @self.mcp.tool()
        async def add_memory(
            content: str,
            user_id: str | None = None,
            conversation_id: str | None = None,
            source: str = "claude-code",
            tags: list[str] | None = None,
        ) -> dict[str, Any]:
            """
            Store a piece of text as a new persistent memory.

            Use this to save important facts, decisions, or user preferences
            that should be remembered across sessions.
            """
            uid = user_id or _default_user_id()
            cid = conversation_id or _default_conversation_id()
            if not uid:
                return {"error": "user_id is required"}
            messages = [{"role": "user", "content": content}]
            resp = self.client.add_message(
                messages=messages,
                user_id=uid,
                conversation_id=cid,
                source=source,
                tags=tags,
            )
            if resp is None:
                return {"error": "add returned None"}
            return resp.model_dump()

        @self.mcp.tool()
        async def get_memory(
            user_id: str | None = None,
            page: int = 1,
            size: int = 20,
        ) -> dict[str, Any]:
            """
            List the user's stored memories (paginated).
            """
            uid = user_id or _default_user_id()
            if not uid:
                return {"error": "user_id is required"}
            resp = self.client.get_memory(user_id=uid, page=page, size=size)
            if resp is None:
                return {"error": "get_memory returned None"}
            return resp.model_dump()

        @self.mcp.tool()
        async def delete_memory(
            memory_ids: list[str],
            user_id: str | None = None,
        ) -> dict[str, Any]:
            """
            Delete specific memories by their IDs.
            """
            uid = user_id or _default_user_id()
            if not uid:
                return {"error": "user_id is required"}
            resp = self.client.delete_memory(
                user_ids=[uid] * len(memory_ids),
                memory_ids=memory_ids,
            )
            if resp is None:
                return {"error": "delete returned None"}
            return resp.model_dump()

        @self.mcp.tool()
        async def chat_with_memory(
            query: str,
            user_id: str | None = None,
            conversation_id: str | None = None,
            system_prompt: str | None = None,
        ) -> dict[str, Any]:
            """
            Send a query to MemOS chat endpoint. The response is
            augmented with relevant memories automatically.
            """
            uid = user_id or _default_user_id()
            cid = conversation_id or _default_conversation_id()
            if not uid:
                return {"error": "user_id is required"}
            resp = self.client.chat(
                user_id=uid,
                conversation_id=cid,
                query=query,
                system_prompt=system_prompt,
            )
            if resp is None:
                return {"error": "chat returned None"}
            return resp.model_dump()

        @self.mcp.tool()
        async def add_feedback(
            feedback_content: str,
            user_id: str | None = None,
            conversation_id: str | None = None,
        ) -> dict[str, Any]:
            """
            Submit explicit user feedback to refine memory quality.
            """
            uid = user_id or _default_user_id()
            cid = conversation_id or _default_conversation_id()
            if not uid:
                return {"error": "user_id is required"}
            resp = self.client.add_feedback(
                user_id=uid,
                conversation_id=cid,
                feedback_content=feedback_content,
            )
            if resp is None:
                return {"error": "add_feedback returned None"}
            return resp.model_dump()

    # ── Run ──────────────────────────────────────────────

    def run(self, transport: str = "sse", **kwargs):
        if transport == "stdio":
            self.mcp.run(transport="stdio")
        elif transport == "sse":
            host = kwargs.get("host", "0.0.0.0")
            port = kwargs.get("port", 8100)
            self.mcp.run(transport="sse", host=host, port=port)
        elif transport == "http":
            import asyncio
            host = kwargs.get("host", "0.0.0.0")
            port = kwargs.get("port", 8100)
            asyncio.run(self.mcp.run_http_async(host=host, port=port))
        else:
            raise ValueError(f"Unsupported transport: {transport}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MemOS Remote MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "sse", "http"], default="sse"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    server = RemoteMCPServer()
    server.run(transport=args.transport, host=args.host, port=args.port)
```

### 2.3 与本地模式 `mcp_serve.py` 的对比

| 维度 | `mcp_serve.py` (本地) | `mcp_serve_remote.py` (远程) |
|------|----------------------|----------------------------|
| 依赖 | MOS 内核 + Neo4j + Qdrant | 仅 `MemOSClient` + HTTP |
| 适用场景 | 开发机 / 单机部署 | 团队共享 / 云端 MemOS |
| 初始化 | 实例化 `MOS(config)` | 实例化 `MemOSClient(api_key)` |
| Tool 粒度 | 底层 CRUD（cube 管理等） | 面向用户的高层操作 |

两者可并存，用户按部署形态选择。

## 3. Skill 定义

Skills 放置在 `.claude/skills/` 目录下（项目级）或 `~/.claude/skills/`（全局级）。每个 Skill 是一个 `.md` 文件，包含 prompt 模板。

### 3.1 `memory-search.md` — 搜索记忆

```markdown
---
name: memory-search
description: Search your persistent memories in MemOS
arguments:
  - name: query
    description: What to search for
    required: true
---

# Memory Search

Use the `search_memory` MCP tool to find relevant memories.

## Instructions

1. Call `search_memory` with the user's query:
   - `query`: "{{query}}"
   - `top_k`: 10
   - `include_preference`: true

2. Format the results:
   - Group by memory type (factual vs preference)
   - Show relevance score if available
   - Quote the memory content directly
   - If no results found, say so clearly

3. Output format:

```
## Memories found for: "{{query}}"

### Factual Memories
- [score] memory content ...

### Preferences
- [score] preference content ...

(N total results)
```

Do NOT fabricate memories. Only show what the tool returns.
```

### 3.2 `memory-store.md` — 存储记忆

```markdown
---
name: memory-store
description: Save important information as a persistent memory
arguments:
  - name: content
    description: The information to remember
    required: true
  - name: tags
    description: Comma-separated tags for categorization
    required: false
---

# Memory Store

Use the `add_memory` MCP tool to persist information.

## Instructions

1. Review the content to store: "{{content}}"

2. Before storing, check if a similar memory already exists:
   - Call `search_memory` with a summary of the content
   - If a near-duplicate exists (same fact), inform the user and skip

3. If no duplicate, call `add_memory`:
   - `content`: "{{content}}"
   - `source`: "claude-code"
   - `tags`: [{{#if tags}}"{{tags}}"{{else}}auto-detect from content{{/if}}]

4. Confirm to the user what was stored.

Do NOT store sensitive information (passwords, API keys, tokens).
If the content appears to contain secrets, warn the user and refuse.
```

### 3.3 `memory-recall.md` — 上下文增强回忆

```markdown
---
name: memory-recall
description: Recall relevant memories for the current coding context
arguments: []
---

# Memory Recall

Automatically recall memories relevant to the current working context.

## Instructions

1. Determine context signals:
   - Current working directory / project name
   - Recent file paths mentioned in conversation
   - Key technical terms from the last few messages

2. Build a search query from these signals (max 200 chars).

3. Call `search_memory` with the constructed query, `top_k`: 5.

4. If results are found, present them as context:

```
## Recalled Memories (auto)

- memory 1 ...
- memory 2 ...

These memories may be relevant to your current task.
```

5. If no results, silently skip — do not output anything.
```

### 3.4 `memory-sync.md` — 对话同步

```markdown
---
name: memory-sync
description: Sync recent conversations into MemOS knowledge base
arguments:
  - name: mode
    description: "once (default) or dry-run"
    required: false
---

# Memory Sync

Trigger the conversation sync pipeline to import recent
Claude Code / Codex / OpenClaw conversations into MemOS.

## Instructions

1. Run the sync script via shell:

```bash
python scripts/sync_conversations_to_kb.py --once {{#if mode}}--{{mode}}{{/if}}
```

2. Parse the script output:
   - Look for the "Sync done. success=N skipped=N failed=N" line
   - Report the counts to the user

3. If `mode` is "dry-run", clarify that no data was actually uploaded.

4. If the script fails, show the error and suggest checking:
   - `MEMOS_SYNC_BASE_URL` and `MEMOS_SYNC_USER_ID` env vars
   - Network connectivity to the MemOS server
```

### 3.5 `memory-manage.md` — 记忆管理

```markdown
---
name: memory-manage
description: List, inspect, or delete stored memories
arguments:
  - name: action
    description: "list, delete, or inspect"
    required: true
  - name: memory_ids
    description: Comma-separated memory IDs (for delete/inspect)
    required: false
  - name: page
    description: Page number for listing
    required: false
---

# Memory Manage

Manage your persistent memories in MemOS.

## Instructions

### action = "list"
1. Call `get_memory` with `page`: {{page | default: 1}}, `size`: 20
2. Display as a numbered list with memory ID and content preview (first 120 chars)
3. Show pagination info (page X, total Y)

### action = "delete"
1. Require `memory_ids` — refuse if not provided
2. Confirm with the user before deleting: "Delete memories: {{memory_ids}}?"
3. On confirmation, call `delete_memory` with the IDs
4. Report success/failure

### action = "inspect"
1. Call `search_memory` or `get_memory` to retrieve full content
2. Display the complete memory with all metadata

Do NOT delete memories without explicit user confirmation.
```

## 4. Claude Code 配置

### 4.1 `settings.json` — MCP Server 注册

在项目根目录 `.claude/settings.json` 或全局 `~/.claude/settings.json` 中添加：

```jsonc
{
  "mcpServers": {
    // 远程模式（推荐：团队共享 MemOS 实例）
    "memos-remote": {
      "type": "sse",
      "url": "http://localhost:8100/sse",
      "env": {
        "MEMOS_API_KEY": "${MEMOS_API_KEY}",
        "MEMOS_BASE_URL": "${MEMOS_BASE_URL}",
        "MEMOS_DEFAULT_USER_ID": "${MEMOS_DEFAULT_USER_ID}"
      }
    }

    // 本地模式（替代方案：开发机直连）
    // "memos-local": {
    //   "type": "stdio",
    //   "command": "python",
    //   "args": ["-m", "memos.api.mcp_serve", "--transport", "stdio"],
    //   "env": {
    //     "OPENAI_API_KEY": "${OPENAI_API_KEY}",
    //     "NEO4J_URI": "${NEO4J_URI}",
    //     "NEO4J_PASSWORD": "${NEO4J_PASSWORD}"
    //   }
    // }
  }
}
```

### 4.2 Skills 安装

将 Section 3 中的 5 个 `.md` 文件放入：

```
.claude/skills/
├── memory-search.md
├── memory-store.md
├── memory-recall.md
├── memory-sync.md
└── memory-manage.md
```

用户通过 `/memory-search "query"` 等斜杠命令触发。

## 5. 环境变量清单

### 5.1 远程 MCP Server 必需

| 变量 | 说明 | 示例 |
|------|------|------|
| `MEMOS_API_KEY` | MemOS OpenMem API Key | `sk-memos-xxx` |
| `MEMOS_BASE_URL` | MemOS API 基础 URL | `https://memos.memtensor.cn/api/openmem/v1` |
| `MEMOS_DEFAULT_USER_ID` | 默认用户 ID（免去每次传参） | `user-abc123` |

### 5.2 远程 MCP Server 可选

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MEMOS_IS_GLOBAL` | 是否使用全球端点 | `false` |
| `MEMOS_DEFAULT_CONVERSATION_ID` | 默认会话 ID | `claude-code` |

### 5.3 对话同步脚本（memory-sync Skill 依赖）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CONVERSATION_SYNC_SINK` | 同步目标 | `memos` |
| `MEMOS_SYNC_BASE_URL` | Product API 地址 | `http://127.0.0.1:8001` |
| `MEMOS_SYNC_USER_ID` | 写入用户 ID | (必填) |
| `MEMOS_SYNC_MEM_CUBE_ID` | 目标 MemCube | (可选) |
| `CONVERSATION_SYNC_AUTO_DISCOVER` | 自动发现本地会话 | `true` |

完整列表参见 `docker/.env.example` 中 `## Daily conversation sync` 段落。

### 5.4 本地模式 MCP Server（如选用）

参见 `docker/.env.example` 中 `## Chat LLM`、`## Embedding & rerank`、`## Graph / vector stores` 段落。核心变量：`OPENAI_API_KEY`、`NEO4J_URI`、`NEO4J_PASSWORD`。

## 6. 测试方案

### 6.1 单元测试 — MCP Server Tools

```python
# tests/api/test_mcp_serve_remote.py

import pytest
from unittest.mock import MagicMock, patch

from memos.api.mcp_serve_remote import RemoteMCPServer


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("MEMOS_API_KEY", "test-key")
    monkeypatch.setenv("MEMOS_BASE_URL", "http://localhost:8001/api/openmem/v1")
    monkeypatch.setenv("MEMOS_DEFAULT_USER_ID", "test-user")


@pytest.fixture
def server(mock_env):
    with patch("memos.api.mcp_serve_remote.MemOSClient") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        srv = RemoteMCPServer()
        srv.client = mock_client
        yield srv, mock_client


class TestSearchMemory:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, server):
        srv, mock_client = server
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {
            "code": 200,
            "data": {"memories": [{"content": "user prefers Python"}]},
        }
        mock_client.search_memory.return_value = mock_resp

        # Get the tool function from FastMCP
        tools = srv.mcp._tool_manager._tools
        result = await tools["search_memory"].fn(query="Python preference")

        assert result["code"] == 200
        mock_client.search_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_missing_user_id(self, server, monkeypatch):
        srv, _ = server
        monkeypatch.delenv("MEMOS_DEFAULT_USER_ID", raising=False)
        # Rebuild to pick up missing env
        with patch("memos.api.mcp_serve_remote._default_user_id", return_value=""):
            tools = srv.mcp._tool_manager._tools
            result = await tools["search_memory"].fn(query="test")
            assert "error" in result


class TestAddMemory:
    @pytest.mark.asyncio
    async def test_add_success(self, server):
        srv, mock_client = server
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {"code": 200, "message": "ok"}
        mock_client.add_message.return_value = mock_resp

        tools = srv.mcp._tool_manager._tools
        result = await tools["add_memory"].fn(content="Remember: deploy on Fridays is banned")

        assert result["code"] == 200
        mock_client.add_message.assert_called_once()


class TestDeleteMemory:
    @pytest.mark.asyncio
    async def test_delete_success(self, server):
        srv, mock_client = server
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {"code": 200}
        mock_client.delete_memory.return_value = mock_resp

        tools = srv.mcp._tool_manager._tools
        result = await tools["delete_memory"].fn(memory_ids=["mem-1", "mem-2"])

        assert result["code"] == 200
        call_args = mock_client.delete_memory.call_args
        assert call_args.kwargs["user_ids"] == ["test-user", "test-user"]
```

### 6.2 集成测试 — 端到端

```bash
# 1. 启动 MemOS Product API（假设已部署）
# 2. 启动远程 MCP Server
export MEMOS_API_KEY="your-key"
export MEMOS_BASE_URL="http://localhost:8001/api/openmem/v1"
export MEMOS_DEFAULT_USER_ID="integration-test-user"
python -m memos.api.mcp_serve_remote --transport sse --port 8100 &

# 3. 用 curl 验证 SSE 端点可达
curl -s http://localhost:8100/sse | head -1
# 应返回 SSE event

# 4. 用 mcp-client CLI 或 Claude Code 调用
# claude> /memory-store "The project uses FastAPI + Neo4j"
# claude> /memory-search "tech stack"
```

### 6.3 Skill 冒烟测试

在 Claude Code 中逐一执行：

| 命令 | 预期行为 |
|------|---------|
| `/memory-store "test fact"` | 调用 `add_memory`，返回确认 |
| `/memory-search "test"` | 调用 `search_memory`，返回刚存的记忆 |
| `/memory-recall` | 根据当前上下文自动搜索 |
| `/memory-manage list` | 调用 `get_memory`，列出记忆 |
| `/memory-manage delete --memory_ids mem-xxx` | 确认后删除 |
| `/memory-sync` | 执行 `sync_conversations_to_kb.py --once` |
| `/memory-sync dry-run` | 执行 dry-run 模式 |

## 7. 与现有对话同步脚本的集成

### 7.1 现状

`scripts/sync_conversations_to_kb.py` 是写入侧：

```
Codex/Claude/OpenClaw 会话文件
        │
        ▼
  sync_conversations_to_kb.py
        │
        ├─ sink=memos  → POST /product/add
        └─ sink=kengine → 导出 .md → K-Engine import API
```

### 7.2 集成方式

`memory-sync` Skill 直接调用该脚本，不做代码修改：

```
用户: /memory-sync
        │
        ▼
  Claude Code 执行 Skill prompt
        │
        ▼
  Bash: python scripts/sync_conversations_to_kb.py --once
        │
        ▼
  解析输出 → 报告 success/skipped/failed 计数
```

如果用户希望定时同步，可在 crontab 或 systemd timer 中直接运行：

```bash
# crontab 示例：每天凌晨 2:30 同步
30 2 * * * cd /path/to/MemOS && python scripts/sync_conversations_to_kb.py --once
```

### 7.3 数据流闭环

```
写入侧（已有）                    读取侧（本设计新增）
─────────────                    ─────────────────
sync_conversations_to_kb.py      MCP search_memory tool
        │                                ▲
        ▼                                │
   MemOS /product/add              MemOS /search/memory
        │                                │
        └──── MemOS 存储层 ──────────────┘
              (Neo4j + Qdrant/Milvus)
```

同步脚本写入的记忆，通过 MCP `search_memory` tool 即可被模型在对话中检索到，形成完整的读写闭环。
