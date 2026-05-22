# EPC2 知识入库系统 — Graph-as-Text 关系说明文档

> 用途：为 Graph-RAG 提供显式的实体与关系定义，作为知识图谱的文本表示。

## 1. 实体清单

### 1.1 系统组件实体

| 实体ID | 实体类型 | 名称 | 说明 |
|--------|---------|------|------|
| `SYS_EPC2` | ExternalSystem | EPC2 | 外部业务系统，文档元数据生产者 |
| `SYS_KS` | Service | knowledge-service | 消息消费、元数据解析、数据库写入 |
| `SYS_ZA` | Service | zhenzhi-adapter | 缓存管理、Kafka 重放、统计查询 |
| `SYS_KAFKA` | MessageQueue | Kafka | 消息中间件 (topic: doc-ingest) |
| `SYS_REDIS` | Cache | Redis | 缓存层 (哨兵模式) |
| `SYS_MYSQL` | Database | MySQL | 持久化存储 |

### 1.2 数据库表实体

| 实体ID | 实体类型 | 名称 | 所属数据库 |
|--------|---------|------|-----------|
| `TBL_UNSTRUCTURED_DOCS` | Table | unstructured_documents | MySQL |
| `TBL_KAFKA_LOGS` | Table | kafka_message_logs | MySQL |
| `TBL_REPO_MAPPINGS` | Table | repo_mappings | MySQL |

### 1.3 约束与索引实体

| 实体ID | 实体类型 | 名称 | 所属表 |
|--------|---------|------|--------|
| `UQ_SYS_FILENUM` | UniqueKey | uq_sys_filenum | TBL_UNSTRUCTURED_DOCS |
| `UQ_SYS_REPO` | UniqueKey | uq_sys_repo | TBL_REPO_MAPPINGS |

### 1.4 接口实体

| 实体ID | 实体类型 | 名称 | 所属服务 |
|--------|---------|------|---------|
| `API_KAFKA_REPLAY` | API | /api/kafka-replay/today | SYS_ZA |
| `API_CACHE_DELETE_ALL` | API | /api/cache/redis/all | SYS_ZA |
| `API_STATS_DAILY` | API | /api/stats/daily | SYS_ZA |
| `API_FILE_STATUS` | API | /api/stats/file-status | SYS_ZA |
| `API_DOC_CALLBACK` | API | /api/doc-ingest/callback | SYS_KS |

### 1.5 缓存 Key 实体

| 实体ID | 实体类型 | Key 模式 | TTL |
|--------|---------|---------|-----|
| `CACHE_STATS_DAILY` | CacheKey | stats:daily:{systemName}:{date} | 300s |
| `CACHE_FILE_STATUS` | CacheKey | file:status:{systemName}:{fileId} | 600s |
| `CACHE_REPO_MAPPING` | CacheKey | repo:mapping:{systemName} | 3600s |
| `CACHE_REPLAY_LOCK` | CacheKey | replay:lock:{systemName} | 60s |

### 1.6 故障实体

| 实体ID | 实体类型 | 错误信息 |
|--------|---------|---------|
| `ERR_DUP_ENTRY` | Error | Duplicate entry 'EPC2-xxx' for key 'uq_sys_filenum' |
| `ERR_CONFIRM_MISMATCH` | Error | confirmation 不匹配，全量缓存清理操作已拒绝 |
| `ERR_CONSUMER_LAG` | Error | Kafka Consumer Lag > 10000 |
| `ERR_CACHE_INCONSISTENT` | Error | Redis 缓存与 MySQL 数据不一致 |
| `ERR_REPLAY_EMPTY` | Error | 当天无可重放记录 |
| `ERR_MAPPING_NOT_FOUND` | Error | repo_mappings 映射不存在或已禁用 |

---

## 2. 关系定义

### 2.1 数据流关系 (DATA_FLOW)

```
[SYS_EPC2]  --PRODUCES-->  [SYS_KAFKA]
[SYS_KAFKA]  --CONSUMES-->  [SYS_KS]
[SYS_KS]     --WRITES_TO--> [TBL_UNSTRUCTURED_DOCS]
[SYS_KS]     --WRITES_TO--> [TBL_KAFKA_LOGS]
[SYS_KS]     --READS_FROM--> [TBL_REPO_MAPPINGS]
[SYS_KS]     --INVALIDATES--> [CACHE_FILE_STATUS]
[SYS_KS]     --INVALIDATES--> [CACHE_STATS_DAILY]
```

### 2.2 查询关系 (QUERIES)

```
[SYS_ZA] --READS_FROM--> [TBL_UNSTRUCTURED_DOCS]
[SYS_ZA] --READS_FROM--> [TBL_KAFKA_LOGS]
[SYS_ZA] --READS_FROM--> [TBL_REPO_MAPPINGS]
[SYS_ZA] --READS_FROM--> [CACHE_STATS_DAILY]
[SYS_ZA] --READS_FROM--> [CACHE_FILE_STATUS]
[SYS_ZA] --READS_FROM--> [CACHE_REPO_MAPPING]
```

### 2.3 接口提供服务关系 (PROVIDES)

```
[SYS_ZA] --PROVIDES--> [API_KAFKA_REPLAY]
[SYS_ZA] --PROVIDES--> [API_CACHE_DELETE_ALL]
[SYS_ZA] --PROVIDES--> [API_STATS_DAILY]
[SYS_ZA] --PROVIDES--> [API_FILE_STATUS]
[SYS_KS] --PROVIDES--> [API_DOC_CALLBACK]
```

### 2.4 接口调用关系 (CALLS)

```
[API_KAFKA_REPLAY]  --READS_FROM--> [TBL_KAFKA_LOGS]
[API_KAFKA_REPLAY]  --PRODUCES_TO--> [SYS_KAFKA]
[API_CACHE_DELETE_ALL] --DELETES--> [CACHE_STATS_DAILY]
[API_CACHE_DELETE_ALL] --DELETES--> [CACHE_FILE_STATUS]
[API_CACHE_DELETE_ALL] --DELETES--> [CACHE_REPO_MAPPING]
[API_CACHE_DELETE_ALL] --REQUIRES--> {confirmation: "I_CONFIRM_DELETE_ALL_REDIS_KEYS"}
[API_STATS_DAILY]    --AGGREGATES_FROM--> [TBL_UNSTRUCTURED_DOCS]
[API_STATS_DAILY]    --CACHES_TO--> [CACHE_STATS_DAILY]
[API_FILE_STATUS]    --LOOKS_UP_IN--> [TBL_UNSTRUCTURED_DOCS]
[API_FILE_STATUS]    --CACHES_TO--> [CACHE_FILE_STATUS]
```

### 2.5 约束关系 (CONSTRAINTS)

```
[UQ_SYS_FILENUM] --ENFORCES_ON--> [TBL_UNSTRUCTURED_DOCS]
[UQ_SYS_FILENUM] --COMPOSED_OF--> {system_name, file_id}
[UQ_SYS_FILENUM] --CAUSES--> [ERR_DUP_ENTRY]
[UQ_SYS_REPO]    --ENFORCES_ON--> [TBL_REPO_MAPPINGS]
[UQ_SYS_REPO]    --COMPOSED_OF--> {system_name, repo_id}
```

### 2.6 故障关联关系 (CAUSED_BY / RESOLVED_BY)

```
[ERR_DUP_ENTRY]          --CAUSED_BY--> [SYS_EPC2] 重复推送
[ERR_DUP_ENTRY]          --DETECTED_BY--> [UQ_SYS_FILENUM]
[ERR_DUP_ENTRY]          --LOGGED_IN--> [TBL_KAFKA_LOGS] (status=4)
[ERR_DUP_ENTRY]          --RESOLVED_BY--> [API_KAFKA_REPLAY]
[ERR_CONSUMER_LAG]       --CAUSED_BY--> [SYS_KS] 资源不足或异常
[ERR_CONSUMER_LAG]       --MONITORED_BY--> Kafka Consumer Group lag 指标
[ERR_CACHE_INCONSISTENT] --CAUSED_BY--> [SYS_REDIS] 写入失败
[ERR_CACHE_INCONSISTENT] --RESOLVED_BY--> [API_CACHE_DELETE_ALL]
[ERR_MAPPING_NOT_FOUND]  --CAUSED_BY--> [TBL_REPO_MAPPINGS] is_active=0 或缺失
[ERR_MAPPING_NOT_FOUND]  --DETECTED_BY--> [SYS_KS] 消费时校验
[ERR_REPLAY_EMPTY]       --RETURNS_FROM--> [API_KAFKA_REPLAY]
```

### 2.7 缓存依赖关系 (DEPENDS_ON)

```
[CACHE_STATS_DAILY]  --DEPENDS_ON--> [TBL_UNSTRUCTURED_DOCS]
[CACHE_FILE_STATUS]  --DEPENDS_ON--> [TBL_UNSTRUCTURED_DOCS]
[CACHE_REPO_MAPPING] --DEPENDS_ON--> [TBL_REPO_MAPPINGS]
```

---

## 3. 关键关系路径

### 3.1 正向入库全链路

```
SYS_EPC2
  --PRODUCES--> SYS_KAFKA(topic:doc-ingest)
    --CONSUMES--> SYS_KS
      --READS_FROM--> TBL_REPO_MAPPINGS
      --WRITES_TO--> TBL_UNSTRUCTURED_DOCS
        --ENFORCED_BY--> UQ_SYS_FILENUM
      --WRITES_TO--> TBL_KAFKA_LOGS
      --INVALIDATES--> CACHE_FILE_STATUS
      --INVALIDATES--> CACHE_STATS_DAILY
```

### 3.2 重放恢复链路

```
API_KAFKA_REPLAY
  --READS_FROM--> TBL_KAFKA_LOGS (status IN (2,4))
  --PRODUCES_TO--> SYS_KAFKA
    --CONSUMES--> SYS_KS (retryFlag=true)
      --READS_FROM--> TBL_UNSTRUCTURED_DOCS (幂等检查)
      --WRITES_TO--> TBL_UNSTRUCTURED_DOCS (补入库)
```

### 3.3 缓存清理影响链路

```
API_CACHE_DELETE_ALL
  --REQUIRES--> confirmation=I_CONFIRM_DELETE_ALL_REDIS_KEYS
  --DELETES--> CACHE_STATS_DAILY
  --DELETES--> CACHE_FILE_STATUS
  --DELETES--> CACHE_REPO_MAPPING
    --FORCES--> API_STATS_DAILY 回源 TBL_UNSTRUCTURED_DOCS
    --FORCES--> API_FILE_STATUS 回源 TBL_UNSTRUCTURED_DOCS
```

---

## 4. 用于 GraphRAG 索引的实体摘要

以下是为 GraphRAG 索引优化的扁平实体列表，每种实体都包含 `id`、`type` 和 `properties`：

```yaml
entities:
  - { id: SYS_EPC2, type: ExternalSystem, props: { lang: Java, role: producer } }
  - { id: SYS_KS, type: Service, props: { lang: Node.js, port: 8081, role: consumer } }
  - { id: SYS_ZA, type: Service, props: { lang: Node.js, port: 8082, role: adapter } }
  - { id: SYS_KAFKA, type: MessageQueue, props: { topic: doc-ingest, partitions: 12 } }
  - { id: SYS_REDIS, type: Cache, props: { mode: sentinel, version: "7.0" } }
  - { id: SYS_MYSQL, type: Database, props: { version: "8.0", engine: InnoDB } }
  - { id: TBL_UNSTRUCTURED_DOCS, type: Table, props: { engine: InnoDB, charset: utf8mb4 } }
  - { id: TBL_KAFKA_LOGS, type: Table, props: { daily_increment: "800000" } }
  - { id: TBL_REPO_MAPPINGS, type: Table, props: { change_rate: low } }
  - { id: UQ_SYS_FILENUM, type: UniqueKey, props: { columns: ["system_name","file_id"] } }
  - { id: UQ_SYS_REPO, type: UniqueKey, props: { columns: ["system_name","repo_id"] } }
  - { id: API_KAFKA_REPLAY, type: API, props: { method: POST, path: /api/kafka-replay/today } }
  - { id: API_CACHE_DELETE_ALL, type: API, props: { method: POST, path: /api/cache/redis/all, requires_confirmation: true } }
  - { id: API_STATS_DAILY, type: API, props: { method: GET, path: /api/stats/daily } }
  - { id: API_FILE_STATUS, type: API, props: { method: GET, path: /api/stats/file-status } }
  - { id: CACHE_STATS_DAILY, type: CacheKey, props: { pattern: "stats:daily:*", ttl: 300 } }
  - { id: CACHE_FILE_STATUS, type: CacheKey, props: { pattern: "file:status:*", ttl: 600 } }
  - { id: CACHE_REPO_MAPPING, type: CacheKey, props: { pattern: "repo:mapping:*", ttl: 3600 } }
  - { id: ERR_DUP_ENTRY, type: Error, props: { severity: P2, table: unstructured_documents } }
  - { id: ERR_CONFIRM_MISMATCH, type: Error, props: { severity: P1 } }
```

## 5. 相关文档索引

- 系统概览与架构：参见 `01_system_overview.md`
- 数据库表结构：参见 `02_database_schema.md`
- 接口文档：参见 `03_api_reference.md`
- Kafka/Redis 流程：参见 `04_kafka_redis_flow.md`
- 故障排查手册：参见 `05_troubleshooting_guide.md`
