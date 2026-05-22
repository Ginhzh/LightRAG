# EPC2 知识入库系统 — Kafka 与 Redis 流程说明

> 消息中间件：Apache Kafka 3.5 | 缓存：Redis 7.0 (哨兵模式)

## 1. Kafka 消息流

### 1.1 Topic 配置

| Topic | 分区数 | 副本数 | 消息保留 | Consumer Group |
|-------|--------|--------|---------|----------------|
| `doc-ingest` | 12 | 3 | 7 天 | `kg-doc-consumer` |
| `doc-parse-result` | 6 | 3 | 3 天 | `kg-parse-consumer` |

### 1.2 消息格式 — DOC_INGEST

EPC2 推送文档入库消息的标准 JSON 格式：

```json
{
  "header": {
    "messageId": "msg-20260510-00001",
    "messageType": "DOC_INGEST",
    "systemName": "EPC2",
    "timestamp": "2026-05-10T14:31:55.123+08:00",
    "version": "1.0"
  },
  "body": {
    "fileId": "DOC-2026-00124577",
    "fileName": "EPC2接口规范_v3.2.pdf",
    "fileType": "pdf",
    "fileSize": 2457600,
    "repoId": "repo-kb-01",
    "metadata": {
      "author": "张三",
      "department": "基础架构部",
      "tags": ["EPC2", "接口文档", "v3.2"],
      "securityLevel": "内部"
    }
  }
}
```

### 1.3 消费流程 (knowledge-service)

```
┌──────────────────────────────────────────────────────────┐
│  knowledge-service Kafka Consumer                        │
│                                                          │
│  1. poll(Duration.ofMillis(500)) 拉取消息                │
│               │                                          │
│  2. 解析 header.messageType，路由到对应处理器            │
│               │                                          │
│  3. 查询 repo_mappings 校验 systemName + repoId          │
│               │                                          │
│     ┌─────────┼─────────┐                                │
│     │ 映射不存在         │ 映射有效                       │
│     ▼                   ▼                                │
│  写入日志            4. INSERT unstructured_documents     │
│  status=3(跳过)           │                               │
│                      ┌────┼────┐                          │
│                      │ 成功    │ 唯一键冲突               │
│                      ▼         ▼                          │
│                   更新缓存   冲突处理                     │
│                              (ON DUPLICATE KEY UPDATE     │
│                               或 status=4 人工处理)       │
│                                                          │
│  5. 写入 kafka_message_logs                              │
│               │                                          │
│  6. 手动 commit offset                                   │
└──────────────────────────────────────────────────────────┘
```

### 1.4 消息重放机制

重放入口为 zhenzhi-adapter 的 `/api/kafka-replay/today`（详见 `03_api_reference.md` 第 2 节）。重放时：

1. **不消费原始 Kafka topic**，而是从 `kafka_message_logs` 表查询消息体。
2. **重新构造 Producer Record**，以 **新消息** 的身份写入 topic `doc-ingest`。
3. 新消息携带 `header.retryFlag: true` 和 `header.originalOffset` 供 knowledge-service 识别。
4. knowledge-service 收到 `retryFlag=true` 的消息时，先查 `unstructured_documents` 是否已存在该 `fileId`，若已存在且 `parse_status=2`，则跳过（防止已成功的记录被覆盖）。

---

## 2. Redis 缓存设计

### 2.1 缓存 Key 规范

| Key 模式 | 类型 | TTL | 说明 |
|----------|------|-----|------|
| `stats:daily:{systemName}:{date}` | Hash | 300s | 每日入库统计 |
| `file:status:{systemName}:{fileId}` | String(JSON) | 600s | 单文件处理状态 |
| `repo:mapping:{systemName}` | String(JSON) | 3600s | 系统-仓库映射列表 |
| `replay:lock:{systemName}` | String | 60s | 重放操作分布式锁 |

### 2.2 缓存读写策略

**stats:daily:* — Cache-Aside 模式**

```
查询请求 ──> Redis GET stats:daily:EPC2:2026-05-10
                │
          ┌─────┼─────┐
          │ hit        │ miss
          ▼            ▼
       直接返回    查询 MySQL:
                  SELECT repo_id, parse_status, COUNT(*)
                  FROM unstructured_documents
                  WHERE system_name='EPC2'
                    AND DATE(created_at)='2026-05-10'
                  GROUP BY repo_id, parse_status
                     │
                     ▼
                  SETEX stats:daily:EPC2:2026-05-10 300 <result>
                     │
                     ▼
                  返回结果
```

**file:status:* — Write-Through + 主动失效**

```javascript
// knowledge-service 写入文档后
await db.insert('unstructured_documents', doc);
await redis.del(`file:status:${systemName}:${fileId}`);
// 下一次访问时回源重建
```

### 2.3 全量缓存清理

调用 `POST /api/cache/redis/all`（参见 `03_api_reference.md` 第 3 节），执行 Redis `SCAN` + `DEL`：

```bash
# 实际执行的 Redis 命令序列
SCAN 0 MATCH stats:daily:* COUNT 1000  # 批量扫描
DEL stats:daily:EPC2:2026-05-10 ...    # 批量删除
SCAN 0 MATCH file:status:* COUNT 1000
DEL file:status:EPC2:DOC-2026-00124577 ...
SCAN 0 MATCH repo:mapping:* COUNT 1000
DEL repo:mapping:EPC2 ...
```

**注意：** `replay:lock:*` 不会被清理（使用独立 SCAN 模式过滤）。

---

## 3. 缓存穿透防护

### 3.1 空值缓存

对于不存在的 `fileId`，Redis 写入空标记：

```javascript
const cached = await redis.get(`file:status:${systemName}:${fileId}`);
if (cached === '__NULL__') {
  return { code: 404, message: '文件不存在' };
}
if (!cached) {
  const dbResult = await db.query(...);
  if (!dbResult) {
    await redis.setex(`file:status:${systemName}:${fileId}`, 60, '__NULL__');
    return { code: 404, message: '文件不存在' };
  }
  await redis.setex(`file:status:${systemName}:${fileId}`, 600, JSON.stringify(dbResult));
  return { code: 0, data: dbResult };
}
return { code: 0, data: JSON.parse(cached) };
```

TTL 60s 的 `__NULL__` 标记确保恶意遍历 fileId 不会击穿数据库。

### 3.2 布隆过滤器（规划中）

对于 `file:status:*` 高频查询，计划引入 RedisBloom 模块，在缓存层之前快速过滤不存在的 `fileId`。

---

## 4. 监控指标

| 指标 | 来源 | 告警阈值 |
|------|------|---------|
| Kafka Consumer Lag | `kafka-consumer-groups` | > 10000 条 |
| Redis 命中率 | `INFO stats` | < 85% |
| 缓存清理耗时 | 应用日志 | > 5s |
| 唯一键冲突率 | `kafka_message_logs.status=4` | > 5% |

---

## 5. 相关文档索引

- 系统架构与组件关系：参见 `01_system_overview.md`
- kafka_message_logs 表结构与查询：参见 `02_database_schema.md` 第 3 节
- 缓存清理与重放接口：参见 `03_api_reference.md`
- 缓存相关的故障排查：参见 `05_troubleshooting_guide.md`
- Kafka/Redis 实体关系：参见 `06_graph_relations.md`
