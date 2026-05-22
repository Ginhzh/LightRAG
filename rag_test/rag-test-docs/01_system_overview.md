# EPC2 知识入库系统 — 系统概览与组件关系

> 版本：v3.2.0 | 最后更新：2026-05-10 | 维护团队：知识平台组

## 1. 系统定位

EPC2 知识入库系统负责将外部业务系统（EPC2）推送的文档元数据，经过消息队列缓冲、元数据解析、去重校验、持久化存储等一系列流程，最终写入知识库供下游检索与推荐服务消费。系统由三个核心服务组成：**knowledge-service**、**zhenzhi-adapter** 和 **EPC2 外部系统**。

## 2. 组件架构

| 组件 | 角色 | 端口 | 技术栈 |
|------|------|------|--------|
| EPC2 | 外部业务系统，文档元数据生产者 | N/A | Java / Spring Boot |
| knowledge-service | 消息消费、元数据解析、数据库写入 | 8081 | Node.js / Express |
| zhenzhi-adapter | 缓存管理、Kafka 重放、统计查询 | 8082 | Node.js / Express |
| Kafka | 消息中间件，解耦 EPC2 与 knowledge-service | 9092 | Apache Kafka 3.5 |
| Redis | 缓存每日统计、处理状态、接口查询结果 | 6379 | Redis 7.0 |
| MySQL | 持久化存储文档主数据、消息日志、仓库映射 | 3306 | MySQL 8.0 |

## 3. 数据流转全景

```
EPC2  ──[文档元数据]──>  Kafka (topic: doc-ingest)  ──>  knowledge-service
                                                              │
                                                    ┌─────────┼─────────┐
                                                    │         │         │
                                                    ▼         ▼         ▼
                                          unstructured_   kafka_     repo_
                                           documents    message_   mappings
                                                         logs
                                                              │
                                                              ▼
                                                     zhenzhi-adapter
                                                      │    │    │
                                                      ▼    ▼    ▼
                                                    Redis 缓存层 (读写)
```

### 3.1 正向入库流程

1. EPC2 产生文档事件，构造 JSON 消息体，发送至 Kafka topic `doc-ingest`。
2. knowledge-service 作为 Kafka Consumer Group `kg-doc-consumer` 的成员，拉取消息。
3. 解析消息中的 `systemName`、`fileId`、`repoId`、`metadata` 等字段。
4. 查询 `repo_mappings` 表，校验 `systemName` + `repoId` 是否在合法映射白名单中。
5. 执行 `INSERT INTO unstructured_documents (...)`，若触发唯一键冲突（`uq_sys_filenum`），进入冲突处理分支。
6. 无论成功或失败，将处理记录写入 `kafka_message_logs`。
7. 写入成功后，清除 Redis 中相关的文件状态缓存和每日统计缓存。

### 3.2 缓存管理流程

- **查询统计**：zhenzhi-adapter 优先读 Redis，miss 时回源 MySQL 并回填缓存（TTL 300s）。
- **缓存清理**：调用 `/api/cache/redis/all`（POST），传入 `confirmation: "I_CONFIRM_DELETE_ALL_REDIS_KEYS"`。
- **Kafka 重放**：调用 `/api/kafka-replay/today`（POST），按 `systemName` + `messageType` 重放当天消息。

## 4. 关键设计决策

| 决策点 | 方案 | 原因 |
|--------|------|------|
| 幂等性保证 | 唯一键 `uq_sys_filenum` | 防止 EPC2 重复推送导致脏数据 |
| 消息可靠性 | Kafka 手动提交 + 消息日志表 | 确保每条消息处理结果可追溯 |
| 缓存穿透防护 | Redis 缓存空值标记（TTL 60s） | 防止高频查询击穿数据库 |
| 重放安全 | confirmation 字段必填 | 防止误操作全量缓存清理 |

## 5. 部署拓扑

```
┌─────────────────────────────────────────────────────────┐
│  Kubernetes Cluster (k-engine-prod)                     │
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ EPC2     │  │ knowledge-   │  │ zhenzhi-adapter  │  │
│  │ (外部)   │  │ service      │  │                  │  │
│  │          │  │ replicas: 3  │  │ replicas: 2      │  │
│  └──────────┘  └──────────────┘  └──────────────────┘  │
│       │               │                    │            │
│       └───────┬───────┘                    │            │
│               │                            │            │
│         ┌─────▼─────┐               ┌──────▼──────┐    │
│         │   Kafka   │               │    Redis    │    │
│         │  (3节点)  │               │  (哨兵模式) │    │
│         └───────────┘               └─────────────┘    │
│                                                         │
│         ┌──────────────────────────┐                    │
│         │        MySQL 8.0         │                    │
│         │    (主从复制, 1主2从)    │                    │
│         └──────────────────────────┘                    │
└─────────────────────────────────────────────────────────┘
```

## 6. 相关文档索引

- 数据库表结构：参见 `02_database_schema.md`
- 接口文档：参见 `03_api_reference.md`
- Kafka/Redis 流程：参见 `04_kafka_redis_flow.md`
- 故障排查：参见 `05_troubleshooting_guide.md`
- 实体关系图：参见 `06_graph_relations.md`
