# 甄知知识库查询与导入接口调用说明

本文档配套脚本：

```bash
bash scripts/kengine_kb_api.sh --help
```

脚本默认读取仓库根目录 `.env`，并使用其中的真实鉴权配置：

- 查询接口：`EXTERNAL_RAG_HEADERS_JSON`
- 导入接口：`KENGINE_IMPORT_HEADERS_JSON` 或 `KENGINE_IMPORT_AUTH_TOKEN`

为避免签名泄漏，脚本不会把签名明文写入 Git 文件，也不会在终端打印鉴权头。
实际 `curl` 请求会在运行时携带 `.env` 中的真实签名。


## 1. 查询接口

查询接口来自 `EXTERNAL_RAG_URL`，请求头来自 `EXTERNAL_RAG_HEADERS_JSON`。

执行：

```bash
bash scripts/kengine_kb_api.sh query "你的查询问题" 5
```

默认请求体与 MemOS `ExternalRAGClient` 保持一致：

```json
{
  "id": "1",
  "content": "你的查询问题",
  "conversationId": "",
  "model": 1,
  "label": "",
  "pluginId": "",
  "questionId": "",
  "tag": "",
  "body": {
    "dataSource": ["knowledge"],
    "language": "cn"
  }
}
```

相关环境变量：

```bash
EXTERNAL_RAG_URL=...
EXTERNAL_RAG_HEADERS_JSON=...
EXTERNAL_RAG_CONVERSATION_ID=...
EXTERNAL_RAG_LANGUAGE=cn
EXTERNAL_RAG_MODEL=1
EXTERNAL_RAG_DATA_SOURCE_JSON='["knowledge"]'
EXTERNAL_RAG_REQUEST_TEMPLATE_JSON=
```

如果 `EXTERNAL_RAG_REQUEST_TEMPLATE_JSON` 非空，脚本会使用模板请求体，
并替换 `{query}`、`{user_id}`、`{conversation_id}` 占位符。


## 2. 导入接口

导入接口来自：

```bash
KENGINE_BASE_URL + KENGINE_IMPORT_PATH
```

当前代码默认路径为：

```text
/path_wiki/wiki/ku/openapi/files/import
```

执行：

```bash
bash scripts/kengine_kb_api.sh import /absolute/or/relative/file.md
```

请求方式：

```text
POST multipart/form-data
```

表单字段：

```text
file            Markdown 文件，type=text/markdown
spaceGuid       空间 GUID
groupGuid       分组 GUID
repositoryGuid  仓库 GUID
```

相关环境变量：

```bash
KENGINE_BASE_URL=...
KENGINE_IMPORT_PATH=/path_wiki/wiki/ku/openapi/files/import
KENGINE_REPO_TRIPLE=spaceGuid/groupGuid/repositoryGuid
KENGINE_IMPORT_HEADERS_JSON=...
KENGINE_IMPORT_AUTH_TOKEN=
KENGINE_IMPORT_TIMEOUT_SECONDS=120
KENGINE_IMPORT_VERIFY_SSL=true
KENGINE_IMPORT_ALLOW_HTTP_FALLBACK=false
```

`KENGINE_REPO_TRIPLE` 也可拆成三个变量：

```bash
KENGINE_SPACE_GUID=...
KENGINE_GROUP_GUID=...
KENGINE_REPOSITORY_GUID=...
```


## 3. 鉴权说明

当前 `.env` 已包含查询和导入所需的 headers JSON：

```bash
EXTERNAL_RAG_HEADERS_JSON=...
KENGINE_IMPORT_HEADERS_JSON=...
```

脚本会把这些 JSON 转成 `curl` header，例如：

```text
Header-Name: Header-Value
```

这些 header 通常包含 cookie、签名、登录态或网关鉴权信息。
不要把它们复制到文档、提交信息、Issue、PR 或聊天记录中。


## 4. 快速验收

查询验收：

```bash
bash scripts/kengine_kb_api.sh query "MemOS 是什么" 5
```

导入验收：

```bash
tmp_file="$(mktemp --suffix=.md)"
printf '# MemOS 导入测试\n\n这是一条甄知知识库导入连通性测试。\n' > "$tmp_file"
bash scripts/kengine_kb_api.sh import "$tmp_file"
rm -f "$tmp_file"
```

成功标志：

- 查询接口返回 JSON 或 SSE 内容，且不是登录页 HTML。
- 导入接口返回 HTTP 2xx，且响应 JSON 中没有 `success=false` 或异常 `code`。


## 5. 与 MemOS 代码的对应关系

查询链路：

- `src/memos/search/external_rag.py`
- `src/memos/api/handlers/search_handler.py`

导入链路：

- `src/memos/api/utils/add_sync.py`
- `scripts/sync_conversations_to_kb.py`
- `scripts/sync_memories_to_kb.py`

`/product/add` 成功后会在 `ADD_MEMORY_SYNC_ENABLED=true` 时执行 best-effort
导入。批量导入则使用 `sync_conversations_to_kb.py` 或
`sync_memories_to_kb.py`。
