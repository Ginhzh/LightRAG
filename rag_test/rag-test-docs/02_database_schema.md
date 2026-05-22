# EPC2 知识入库系统 — 数据库表结构与唯一键说明

> 数据库：MySQL 8.0 | 引擎：InnoDB | 字符集：utf8mb4 | 排序规则：utf8mb4_unicode_ci

## 1. 表概览

| 表名 | 用途 | 预估日增量 | 关键索引 |
|------|------|-----------|---------|
| `unstructured_documents` | 文档主数据存储 | ~50w 行 | `uq_sys_filenum`, `idx_repo_id`, `idx_created_at` |
| `kafka_message_logs` | Kafka 消息处理记录 | ~80w 行 | `idx_msg_id`, `idx_created_at`, `idx_status` |
| `repo_mappings` | 业务系统→仓库映射 | ~500 行（低变更） | `uq_sys_repo`, `idx_system_name` |

---

## 2. unstructured_documents 表

### 2.1 表结构

```sql
CREATE TABLE `unstructured_documents` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `system_name` VARCHAR(64) NOT NULL COMMENT '来源系统名称，如 EPC2',
  `file_id` VARCHAR(128) NOT NULL COMMENT '业务系统内文件唯一标识',
  `file_name` VARCHAR(512) DEFAULT NULL COMMENT '原始文件名',
  `file_type` VARCHAR(32) DEFAULT NULL COMMENT '文件类型: pdf/docx/xlsx/txt/md',
  `file_size` BIGINT UNSIGNED DEFAULT 0 COMMENT '文件大小(字节)',
  `repo_id` VARCHAR(64) NOT NULL COMMENT '目标知识库仓库ID',
  `metadata_json` JSON DEFAULT NULL COMMENT '原始元数据JSON',
  `parse_status` TINYINT NOT NULL DEFAULT 0 COMMENT '解析状态: 0待处理 1处理中 2成功 3失败',
  `parse_error_msg` VARCHAR(1024) DEFAULT NULL COMMENT '解析失败原因',
  `kafka_offset` BIGINT DEFAULT NULL COMMENT '来源Kafka消息offset',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sys_filenum` (`system_name`, `file_id`),
  KEY `idx_repo_id` (`repo_id`),
  KEY `idx_created_at` (`created_at`),
  KEY `idx_parse_status` (`parse_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 2.2 唯一键 uq_sys_filenum 详解

**组成：** `system_name` + `file_id`

**作用：**
- 确保同一业务系统的同一文件不会被重复入库
- 实现写入幂等性：INSERT 失败时可安全转为 UPDATE 或 IGNORE

**冲突场景：** EPC2 因网络重试或回调异常，对同一 `file_id` 发起两次推送。第二次 INSERT 触发：

```
Error: Duplicate entry 'EPC2-DOC-2026-00124578' for key 'uq_sys_filenum'
```

**处理策略（knowledge-service 中实现）：**

| 策略 | 适用场景 | 实现 |
|------|---------|------|
| INSERT IGNORE | 元数据无变化的重推 | 直接忽略，记录日志 |
| ON DUPLICATE KEY UPDATE | 元数据可能有更新 | 更新 `file_name`, `file_size`, `metadata_json`, `updated_at` |
| 报错 + 人工处理 | 不确定是否应覆盖 | 写入 `kafka_message_logs` 标记 status=4（冲突待处理） |

### 2.3 示例数据

```sql
SELECT id, system_name, file_id, repo_id, parse_status, created_at
FROM unstructured_documents
WHERE system_name = 'EPC2'
ORDER BY created_at DESC
LIMIT 5;
```

| id | system_name | file_id | repo_id | parse_status | created_at |
|----|-------------|---------|---------|-------------|------------|
| 1823457 | EPC2 | DOC-2026-00124578 | repo-kb-01 | 2 | 2026-05-10 14:32:01 |
| 1823456 | EPC2 | DOC-2026-00124577 | repo-kb-01 | 2 | 2026-05-10 14:31:55 |
| 1823455 | EPC2 | DOC-2026-00124576 | repo-kb-02 | 0 | 2026-05-10 14:31:48 |

---

## 3. kafka_message_logs 表

### 3.1 表结构

```sql
CREATE TABLE `kafka_message_logs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `topic` VARCHAR(128) NOT NULL COMMENT 'Kafka topic',
  `partition` INT NOT NULL COMMENT '分区号',
  `offset` BIGINT NOT NULL COMMENT '消息offset',
  `message_key` VARCHAR(256) DEFAULT NULL COMMENT '消息key',
  `message_body` JSON NOT NULL COMMENT '原始消息体',
  `message_type` VARCHAR(32) NOT NULL COMMENT '消息类型: DOC_INGEST/DOC_UPDATE/DOC_DELETE',
  `status` TINYINT NOT NULL DEFAULT 0 COMMENT '0待处理 1成功 2失败 3跳过 4冲突待处理',
  `error_msg` VARCHAR(2048) DEFAULT NULL COMMENT '失败或冲突原因',
  `retry_count` INT NOT NULL DEFAULT 0 COMMENT '重试次数',
  `process_time_ms` INT DEFAULT NULL COMMENT '处理耗时(毫秒)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_msg_id` (`topic`, `partition`, `offset`),
  KEY `idx_created_at` (`created_at`),
  KEY `idx_status` (`status`),
  KEY `idx_type_status` (`message_type`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 3.2 消息重放的查询基础

`/api/kafka-replay/today` 接口依赖此表筛选当天待重放的消息：

```sql
SELECT id, topic, `partition`, `offset`, message_body, message_type
FROM kafka_message_logs
WHERE DATE(created_at) = CURDATE()
  AND status IN (2, 4)  -- 失败和冲突待处理
ORDER BY id ASC;
```

---

## 4. repo_mappings 表

### 4.1 表结构

```sql
CREATE TABLE `repo_mappings` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `system_name` VARCHAR(64) NOT NULL COMMENT '业务系统名称',
  `repo_id` VARCHAR(64) NOT NULL COMMENT '知识库仓库ID',
  `repo_name` VARCHAR(256) DEFAULT NULL COMMENT '仓库名称',
  `is_active` TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用: 0禁用 1启用',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sys_repo` (`system_name`, `repo_id`),
  KEY `idx_system_name` (`system_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 4.2 映射示例

| system_name | repo_id | repo_name | is_active |
|-------------|---------|-----------|-----------|
| EPC2 | repo-kb-01 | 技术知识库 | 1 |
| EPC2 | repo-kb-02 | 产品文档库 | 1 |
| EPC2 | repo-kb-03 | 运维手册库 | 0 |

`is_active=0` 的映射将导致对应文档被跳过，适用于仓库下线但保留映射记录的场景。

---

## 5. 索引优化建议

1. **kafka_message_logs 高频查询**：`idx_type_status` 覆盖重放查询，建议联合索引 `(message_type, status, created_at)` 以优化范围扫描。
2. **unstructured_documents 统计查询**：每日统计需 `COUNT` + `GROUP BY repo_id` 和 `parse_status`，建议联合索引 `(repo_id, parse_status, created_at)`。
3. **分区建议**：`kafka_message_logs` 日增量 80w+，建议按 `created_at` 按月 RANGE 分区，保留 6 个月数据。

---

## 6. 相关文档索引

- 系统概览与数据流转：参见 `01_system_overview.md`
- Kafka 消息重放接口：参见 `03_api_reference.md` 第 3 节
- Redis 缓存 Key 设计与 kafka_message_logs 的关系：参见 `04_kafka_redis_flow.md`
- 唯一键冲突故障排查：参见 `05_troubleshooting_guide.md`
- 实体关系图：参见 `06_graph_relations.md`
