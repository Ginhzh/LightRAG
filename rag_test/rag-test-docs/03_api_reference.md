# EPC2 知识入库系统 — 接口文档

> 基础路径：`https://k-engine.internal/api` | 认证方式：Bearer Token (JWT)

## 1. 接口总览

| 方法 | 路径 | 服务 | 用途 |
|------|------|------|------|
| POST | `/api/kafka-replay/today` | zhenzhi-adapter | 重放当天 Kafka 消息 |
| POST | `/api/cache/redis/all` | zhenzhi-adapter | 全量清理 Redis 缓存 |
| GET | `/api/stats/daily` | zhenzhi-adapter | 查询当日入库统计 |
| GET | `/api/stats/file-status` | zhenzhi-adapter | 按 file_id 查询文件处理状态 |
| POST | `/api/doc-ingest/callback` | knowledge-service | EPC2 文档入库回调 |

---

## 2. POST /api/kafka-replay/today

### 2.1 功能说明

按 `systemName` 和 `messageType` 筛选 `kafka_message_logs` 表中当天状态为失败(2)或冲突待处理(4)的记录，重新投递到 Kafka topic `doc-ingest`，由 knowledge-service 再次消费处理。

### 2.2 请求

```http
POST /api/kafka-replay/today HTTP/1.1
Host: k-engine.internal
Authorization: Bearer [REDACTED_JWT]
Content-Type: application/json

{
  "systemName": "EPC2",
  "messageType": "DOC_INGEST"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| systemName | string | 是 | 来源系统，如 `EPC2` |
| messageType | string | 是 | 消息类型：`DOC_INGEST` / `DOC_UPDATE` / `DOC_DELETE` |

### 2.3 成功响应

```json
{
  "code": 0,
  "message": "重放任务已提交",
  "data": {
    "replayId": "rp-20260510-001",
    "totalCount": 47,
    "systemName": "EPC2",
    "messageType": "DOC_INGEST",
    "estimatedDurationSec": 30
  }
}
```

### 2.4 错误响应

```json
{
  "code": 40001,
  "message": "参数缺失: systemName 为必填项",
  "data": null
}
```

```json
{
  "code": 40002,
  "message": "当天无可重放记录: EPC2 / DOC_DELETE",
  "data": { "systemName": "EPC2", "messageType": "DOC_DELETE", "availableCount": 0 }
}
```

### 2.5 内部执行流程

1. 校验 `systemName` 和 `messageType` 合法性。
2. 查询 `kafka_message_logs`（SQL 参见 `02_database_schema.md` 第 3.2 节）。
3. 对每条待重放记录，构造 Kafka Producer Record，写入 topic `doc-ingest`。
4. 更新 `kafka_message_logs.retry_count = retry_count + 1`。
5. 清除 Redis Key `stats:daily:{systemName}` (使统计缓存失效)。
6. 返回重放摘要。

---

## 3. POST /api/cache/redis/all

### 3.1 功能说明

清理 Redis 全量缓存（危险操作）。**必须**传入确认字段，防止误触发。

### 3.2 请求

```http
POST /api/cache/redis/all HTTP/1.1
Host: k-engine.internal
Authorization: Bearer [REDACTED_JWT]
Content-Type: application/json

{
  "confirmation": "I_CONFIRM_DELETE_ALL_REDIS_KEYS"
}
```

### 3.3 成功响应

```json
{
  "code": 0,
  "message": "全量缓存已清理",
  "data": {
    "deletedKeys": 12834,
    "freedMemoryMB": 256,
    "timestamp": "2026-05-10T15:30:00+08:00"
  }
}
```

### 3.4 安全校验失败

```json
{
  "code": 40301,
  "message": "confirmation 不匹配，全量缓存清理操作已拒绝。正确值为: I_CONFIRM_DELETE_ALL_REDIS_KEYS",
  "data": null
}
```

### 3.5 影响范围

执行后，以下 Redis 缓存将被清空（详见 `04_kafka_redis_flow.md`）：

| 缓存 Key 模式 | 影响 |
|--------------|------|
| `stats:daily:*` | 每日统计接口回源 MySQL，QPS 升高 |
| `file:status:*` | 文件状态查询延迟上升至 ~200ms |
| `repo:mapping:*` | 仓库映射每次查询均回源 DB |

---

## 4. GET /api/stats/daily

### 4.1 功能说明

查询某系统当天的文档入库统计数据。优先读 Redis，miss 时回源 `unstructured_documents` 表。

### 4.2 请求

```http
GET /api/stats/daily?systemName=EPC2&date=2026-05-10 HTTP/1.1
Authorization: Bearer [REDACTED_JWT]
```

### 4.3 响应

```json
{
  "code": 0,
  "data": {
    "systemName": "EPC2",
    "date": "2026-05-10",
    "totalReceived": 15230,
    "successCount": 14987,
    "failCount": 196,
    "conflictCount": 47,
    "avgProcessTimeMs": 85
  }
}
```

---

## 5. GET /api/stats/file-status

### 5.1 功能说明

按 `systemName` + `fileId` 精确查询单个文件的处理状态，适合集成调试和故障排查。

### 5.2 请求

```http
GET /api/stats/file-status?systemName=EPC2&fileId=DOC-2026-00124578 HTTP/1.1
Authorization: Bearer [REDACTED_JWT]
```

### 5.3 响应

```json
{
  "code": 0,
  "data": {
    "systemName": "EPC2",
    "fileId": "DOC-2026-00124578",
    "parseStatus": 2,
    "parseStatusText": "解析成功",
    "repoId": "repo-kb-01",
    "kafkaOffset": 98234001,
    "createdAt": "2026-05-10T14:32:01+08:00"
  }
}
```

### 5.4 状态码说明

| parse_status | 含义 | 说明 |
|-------------|------|------|
| 0 | 待处理 | 已入库，等待下游解析服务消费 |
| 1 | 处理中 | 解析服务正在处理 |
| 2 | 成功 | 解析完成，文档可检索 |
| 3 | 失败 | 解析失败，详见 parse_error_msg |
| 4 | 冲突待处理 | 唯一键冲突，等待人工决策 |

---

## 6. 公共错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 40001 | 参数缺失 |
| 40002 | 参数无效或无可处理数据 |
| 40100 | Token 过期或无效 |
| 40300 | 权限不足 |
| 40301 | 安全校验失败 (如 confirmation 不匹配) |
| 50000 | 内部服务异常 |

---

## 7. 相关文档索引

- 数据库表结构（消息日志、文档表）：参见 `02_database_schema.md`
- Kafka 重放与 Redis 缓存流程：参见 `04_kafka_redis_flow.md`
- 统计接口 Redis 缓存策略：参见 `04_kafka_redis_flow.md` 第 2 节
- 常见错误排查：参见 `05_troubleshooting_guide.md`
- API 调用链路关系：参见 `06_graph_relations.md`
