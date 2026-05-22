# MemOS 外部 RAG + 对话同步改造复用指南

## 1. 本次改造范围总览

这次改造把 MemOS 做成了两条并行能力：

1. `外部 RAG 检索接管`：`/product/search` 可以按开关或 `source` 路由到你的外部检索接口。
2. `对话归档同步`：按日把 Codex / Claude / OpenClaw 对话清洗后写入知识库（MemOS 或 K-Engine 文件导入）。

核心改动文件：

- `src/memos/search/external_rag.py`
- `src/memos/api/handlers/search_handler.py`
- `src/memos/search/__init__.py`
- `scripts/sync_conversations_to_kb.py`
- `docker/.env.example`
- `tests/search/test_external_rag.py`
- `tests/search/test_sync_conversations_to_kb.py`
- `src/memos/embedders/ark.py`
- `src/memos/parsers/markitdown.py`
- `src/memos/memories/activation/kv.py`
- `tests/memories/activation/test_kv.py`

---

## 2. 外部 RAG 接入设计（可直接复用）

### 2.1 接入点与路由逻辑

- 搜索处理器初始化外部客户端：`src/memos/api/handlers/search_handler.py:47`
- 每次请求先判断是否由外部 RAG 接管：`src/memos/api/handlers/search_handler.py:71`
- 外部检索失败会自动回退到原生 MemOS 检索：`src/memos/api/handlers/search_handler.py:773`

触发条件（任一满足）：

- `ENABLE_EXTERNAL_RAG=true`
- 请求体 `source == EXTERNAL_RAG_SOURCE_TAG`

对应逻辑：`src/memos/search/external_rag.py:137`

### 2.2 请求与响应契约

外部客户端：`ExternalRAGClient`（`src/memos/search/external_rag.py:85`）

默认请求体构造（可模板化覆盖）：`src/memos/search/external_rag.py:175`

默认字段：

- `content`：查询词
- `conversationId`：会话 id
- `model`
- `body.dataSource`
- `body.language`

模板能力：

- 通过 `EXTERNAL_RAG_REQUEST_TEMPLATE_JSON` 定义任意请求 JSON
- 占位符：`{query}`、`{user_id}`、`{conversation_id}`
- 模板渲染逻辑：`src/memos/search/external_rag.py:72`

响应解析能力：

- 普通 JSON：`src/memos/search/external_rag.py:169`
- SSE 流：`src/memos/search/external_rag.py:212`
- 可配置 items 路径抽取：`EXTERNAL_RAG_ITEMS_PATH`，逻辑见 `src/memos/search/external_rag.py:199`

最终标准化为 MemOS `text_mem.memories[]` 结构，见：`src/memos/search/external_rag.py:344`

### 2.3 环境变量

定义在 `docker/.env.example:96` 起：

- `ENABLE_EXTERNAL_RAG`
- `EXTERNAL_RAG_URL`
- `EXTERNAL_RAG_SOURCE_TAG`
- `EXTERNAL_RAG_HEADERS_JSON`
- `EXTERNAL_RAG_TIMEOUT_SECONDS`
- `EXTERNAL_RAG_ITEMS_PATH`
- `EXTERNAL_RAG_REQUEST_TEMPLATE_JSON`
- `EXTERNAL_RAG_SSE_STOP_ON_SOURCE`
- `EXTERNAL_RAG_SSE_MAX_EVENTS`

### 2.4 在其它项目的最小迁移步骤

1. 复制 `ExternalRAGClient` 到目标项目。
2. 在搜索入口增加 `should_handle(source)` 判断。
3. 外部调用失败时必须回退本地检索。
4. 把外部结果统一映射为内部检索结果结构，减少上层改动。
5. 给外部路径补单元测试（JSON + SSE 两套）。

---

## 3. 对话同步与知识库导入（可直接复用）

脚本入口：`scripts/sync_conversations_to_kb.py:1`

### 3.1 数据源发现

支持三类来源：

- 手工指定文件：`CODEX_CONVERSATION_FILE` / `CLAUDE_CONVERSATION_FILE` / `OPENCLAW_CONVERSATION_FILE`（`scripts/sync_conversations_to_kb.py:616`）
- 额外 JSON 配置源：`CONVERSATION_SYNC_SOURCES_JSON`（`scripts/sync_conversations_to_kb.py:629`）
- 自动发现本地历史：`~/.codex`、`~/.claude`、`~/.openclaw`（`scripts/sync_conversations_to_kb.py:657`）

会对 `(kind, path)` 去重：`scripts/sync_conversations_to_kb.py:695`

### 3.2 清洗治理策略

核心治理逻辑：

- 去除思维链/工具中间消息：`scripts/sync_conversations_to_kb.py:165`
- 统一角色（user/assistant）：`scripts/sync_conversations_to_kb.py:249`
- 过滤 harness 噪声与 slash 命令：`scripts/sync_conversations_to_kb.py:260`
- 脱敏（邮箱/手机号/Bearer/token）：`scripts/sync_conversations_to_kb.py:284`
- 长文本截断：`scripts/sync_conversations_to_kb.py:296`

幂等控制：

- 历史指纹状态：`.memos/conversation_sync_state.json`（`scripts/sync_conversations_to_kb.py:716`）
- 运行内重复过滤：`scripts/sync_conversations_to_kb.py:755`

### 3.3 导出格式

按会话导出 Markdown：`scripts/sync_conversations_to_kb.py:901`

结构：

- Session 元数据（source、conversation_id、时间区间、来源文件）
- `## Conversation`
- `### [timestamp] role` + 正文

文件命名：`{source}_{date}_{conversation_id}.md`，见 `scripts/sync_conversations_to_kb.py:955`

### 3.4 下游写入模式

两种 sink（`CONVERSATION_SYNC_SINK`）：

- `memos`：直接打 `/product/add`（`scripts/sync_conversations_to_kb.py:776`）
- `kengine`：先导出 md，再调用文件导入 API（`scripts/sync_conversations_to_kb.py:972`）

---

## 4. K-Engine 文件导入实现

### 4.1 接口映射

实现函数：`_upload_file_to_kengine`（`scripts/sync_conversations_to_kb.py:846`）

请求 URL 组装：

- 默认 base：`https://k-engine.weichai.com`
- 默认 path：`/path_wiki/wiki/ku/openapi/files/import`
- 逻辑：`scripts/sync_conversations_to_kb.py:836`

multipart 字段：

- `file`
- `spaceGuid`
- `groupGuid`
- `repositoryGuid`

对应代码：`scripts/sync_conversations_to_kb.py:863`

### 4.2 GUID 参数策略

支持两种方式：

- `KENGINE_REPO_TRIPLE=space/group/repository`（`scripts/sync_conversations_to_kb.py:818`）
- 或三个独立变量：`KENGINE_SPACE_GUID` / `KENGINE_GROUP_GUID` / `KENGINE_REPOSITORY_GUID`

### 4.3 常见故障

- GUID 不全：启动即报错（参数校验失败）。
- headers JSON 非法：仅告警并忽略额外头。
- 导入 4xx/5xx：记录失败日志，不自动重试。

建议在其它项目增加：

1. 指数退避重试。
2. 失败文件重放队列。
3. 上传结果审计落库。

---

## 5. 兼容性修复（可复用模式）

### 5.1 可选依赖懒加载

- Ark embedder 从“导入时强依赖”改为“运行时 require”
- 文件：`src/memos/embedders/ark.py:29`
- 缺失依赖时给出清晰安装提示：`src/memos/embedders/ark.py:37`

复用原则：可选 SDK 一律 lazy import，避免服务启动即崩。

### 5.2 解析器降级

- `markitdown` 不可用时，降级到轻量文本/PDF 提取
- 文件：`src/memos/parsers/markitdown.py:35`

复用原则：高能力 parser + 轻量 fallback 双轨，保证可用性。

### 5.3 版本兼容抽象层

- DynamicCache 新旧结构统一通过 getter/setter 兼容
- 文件：`src/memos/memories/activation/kv.py:213`

复用原则：对第三方库不稳定结构加中间抽象，并配双版本测试。

---

## 6. 测试覆盖与验收

新增/关键测试：

- 外部 RAG：`tests/search/test_external_rag.py:63`
- 对话同步：`tests/search/test_sync_conversations_to_kb.py:19`
- KV 兼容：`tests/memories/activation/test_kv.py:13`

建议在其它项目采用相同验收顺序：

1. 单测：外部 RAG（JSON + SSE）。
2. 单测：对话清洗（噪声过滤、角色归一、脱敏）。
3. 单测：导出命名与结构稳定性。
4. 集成：真实导入接口（至少一份 md）。
5. 回归：全量测试后再切换生产配置。

---

## 7. 迁移到其它项目的落地清单

1. 新增 `ExternalRAGClient` + 搜索入口路由接管。
2. 在配置中心新增外部 RAG 与同步任务全部 env 变量。
3. 复制 `sync_conversations_to_kb.py`，保留清洗/脱敏/幂等逻辑。
4. 根据目标知识库实现 sink（memos/kengine/其他）。
5. 为文件导入加重试与死信处理。
6. 配置每日定时（crontab/systemd/k8s CronJob 任一）。
7. 用测试样例覆盖关键路径后再上线。

---

## 8. 推荐定时任务命令

单次跑一轮：

```bash
python scripts/sync_conversations_to_kb.py --once
```

先演练不入库：

```bash
python scripts/sync_conversations_to_kb.py --once --dry-run
```

每天定时（示例 02:30）：

```bash
python scripts/sync_conversations_to_kb.py --daily-at 02:30
```

---

## 9. 关键经验总结

- 外部 RAG 接入最重要的是“可回退”，否则上游波动会直接影响搜索可用性。
- 对话同步必须先治理再入库，不然知识库污染会迅速放大。
- 文件导入接口要按“幂等 + 可重放”设计，避免一次失败导致长期数据缺口。
- 兼容性修复（可选依赖、fallback、版本抽象）是长期稳定运行的基础设施。
