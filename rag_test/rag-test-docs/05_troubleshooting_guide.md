# EPC2 知识入库系统 — 常见故障排查手册

> 维护团队：知识平台组 | 值班钉钉群：k-engine-oncall

## 1. 故障分类索引

| 故障类型 | 典型现象 | 影响范围 | 优先级 |
|---------|---------|---------|--------|
| 唯一键冲突 | `Duplicate entry 'EPC2-xxx' for key 'uq_sys_filenum'` | 单条文档入库失败 | P2 |
| Kafka 消费积压 | Consumer Lag > 10000 | 全局入库延迟 | P0 |
| Redis 缓存不一致 | 统计数与实际不符 | 统计查询结果偏差 | P1 |
| 消息重放失败 | `/api/kafka-replay/today` 返回空或报错 | 失败消息无法自动恢复 | P1 |
| 映射配置错误 | 文档入库后查不到 | 特定 repo 的文档全量丢失 | P0 |

---

## 2. 故障一：唯一键冲突 Duplicate Entry

### 2.1 错误日志示例

```
2026-05-10 14:32:01.234 ERROR [knowledge-service] [kg-doc-consumer-2]
  KafkaMessageHandler - 文档入库失败
  topic=doc-ingest partition=3 offset=98234002
  systemName=EPC2 fileId=DOC-2026-00124578 repoId=repo-kb-01
  Error: ER_DUP_ENTRY: Duplicate entry 'EPC2-DOC-2026-00124578' for key 'uq_sys_filenum'
  at Query.Sequence._packetToError (/app/node_modules/mysql2/lib/packets/packet.js:728:13)
  ---
  Action: 已写入 kafka_message_logs, status=4 (冲突待处理), retry_count=0
```

### 2.2 排查步骤

**Step 1 — 确认是否为合法重推**

```sql
-- 查看已存在记录的详情
SELECT id, file_id, file_name, repo_id, parse_status, created_at, updated_at
FROM unstructured_documents
WHERE system_name = 'EPC2' AND file_id = 'DOC-2026-00124578';
```

**Step 2 — 对比新旧消息内容**

```sql
-- 查看冲突消息体
SELECT id, message_body, created_at
FROM kafka_message_logs
WHERE JSON_EXTRACT(message_body, '$.body.fileId') = 'DOC-2026-00124578'
ORDER BY created_at DESC;
```

**Step 3 — 决策**

| 场景 | 操作 |
|------|------|
| 元数据无变化 | 忽略 — 这是 EPC2 的正常重试 |
| 元数据有更新（如文件名变更） | 手动执行 UPDATE 更新元数据字段 |
| 不确定 | 保留 status=4，由值班人员决策 |

### 2.3 批量处理冲突

```sql
-- 查询所有待处理的唯一键冲突
SELECT DATE(created_at) AS dt, COUNT(*) AS cnt
FROM kafka_message_logs
WHERE message_type = 'DOC_INGEST' AND status = 4
GROUP BY DATE(created_at)
ORDER BY dt DESC;
```

冲突率超过 5% 时需通知 EPC2 侧排查推送逻辑（参见 `01_system_overview.md` 系统架构中 EPC2 的职责边界）。

---

## 3. 故障二：Kafka 消费积压

### 3.1 现象

- zhenzhi-adapter `/api/stats/daily` 返回的 `totalReceived` 明显低于 EPC2 侧推送量
- 监控平台 Consumer Lag 持续上升

### 3.2 排查步骤

```bash
# 1. 检查 Consumer Group 状态
kafka-consumer-groups --bootstrap-server kafka:9092 \
  --group kg-doc-consumer --describe

# 预期输出：LAG 列应 < 500 (正常)
# 异常：LAG > 10000 且持续增长
```

```sql
-- 2. 检查最近处理速率
SELECT
  DATE_FORMAT(created_at, '%Y-%m-%d %H:%i') AS minute,
  COUNT(*) AS processed_count
FROM kafka_message_logs
WHERE created_at > DATE_SUB(NOW(), INTERVAL 30 MINUTE)
GROUP BY DATE_FORMAT(created_at, '%Y-%m-%d %H:%i')
ORDER BY minute DESC;
```

**3. 检查 knowledge-service Pod 状态**

```bash
kubectl get pods -l app=knowledge-service -n k-engine-prod
kubectl logs -l app=knowledge-service --tail=100 | grep -E "ERROR|WARN|OOM|timeout"
```

### 3.3 恢复方案

| 原因 | 操作 |
|------|------|
| Pod 资源不足 | 扩容 replicas 或增加 CPU/Memory limit |
| 数据库慢查询 | 检查 `unstructured_documents` 索引，分析慢查询日志 |
| 下游解析服务阻塞 | 临时关闭解析触发，让入库先跑通，积压消化后再开启 |
| 网络抖动 | 检查 Kafka 连接，必要时重启 Consumer |

---

## 4. 故障三：Redis 缓存不一致

### 4.1 现象

`/api/stats/daily` 返回的统计数和直接查询 `unstructured_documents` 表得到的数据不一致。

### 4.2 根本原因

knowledge-service 写入后 Redis 缓存清除失败（Redis 连接超时 / 网络闪断），导致后续查询命中旧缓存。

### 4.3 排查与修复

```bash
# 1. 对比缓存值与数据库值
redis-cli GET "stats:daily:EPC2:2026-05-10"

# 直接在 MySQL 执行
mysql> SELECT repo_id, parse_status, COUNT(*) AS cnt
       FROM unstructured_documents
       WHERE system_name='EPC2' AND DATE(created_at)='2026-05-10'
       GROUP BY repo_id, parse_status;
```

如果不一致：

```bash
# 2. 清除对应 Key
redis-cli DEL "stats:daily:EPC2:2026-05-10"
```

或者调用接口强制全量清理（**需要 confirmation**）：

```bash
curl -X POST https://k-engine.internal/api/cache/redis/all \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"confirmation":"I_CONFIRM_DELETE_ALL_REDIS_KEYS"}'
```

接口详情参见 `03_api_reference.md` 第 3 节，缓存 Key 规范参见 `04_kafka_redis_flow.md` 第 2.1 节。

---

## 5. 故障四：消息重放无效果

### 5.1 现象

调用 `/api/kafka-replay/today` 后，失败记录仍未恢复。

### 5.2 排查清单

- [ ] 确认 `systemName` 和 `messageType` 拼写正确（大小写敏感）
- [ ] 确认当天确实有 status=2 或 status=4 的记录
- [ ] 检查 knowledge-service 是否正在运行
- [ ] 检查 `kafka_message_logs.retry_count`，超过 3 次的记录不会自动重放
- [ ] 查看重放时的应用日志：`grep "replay" /var/log/zhenzhi-adapter/app.log`

### 5.3 手动恢复

```sql
-- 重置重试次数（谨慎使用）
UPDATE kafka_message_logs
SET retry_count = 0, status = 0
WHERE status = 2 AND retry_count >= 3
  AND message_type = 'DOC_INGEST'
  AND DATE(created_at) = CURDATE();
```

然后再次调用 `/api/kafka-replay/today`。

---

## 6. 故障五：repo_mappings 配置错误

### 6.1 现象

EPC2 推送的文档在 `kafka_message_logs` 中 status=3（跳过），错误信息为 `systemName=EPC2, repoId=repo-kb-03 映射不存在或已禁用`。

### 6.2 修复

```sql
-- 检查映射状态
SELECT * FROM repo_mappings
WHERE system_name = 'EPC2' AND repo_id = 'repo-kb-03';

-- 如果存在但 is_active=0，启用之
UPDATE repo_mappings SET is_active = 1
WHERE system_name = 'EPC2' AND repo_id = 'repo-kb-03';

-- 如果不存在，插入新映射
INSERT INTO repo_mappings (system_name, repo_id, repo_name, is_active)
VALUES ('EPC2', 'repo-kb-03', '运维手册库', 1);
```

之后对受影响的消息执行重放（参见第 5 节）。

---

## 7. 相关文档索引

- 系统架构与组件：参见 `01_system_overview.md`
- 表结构与唯一键说明：参见 `02_database_schema.md`
- 缓存清理接口 `/api/cache/redis/all`：参见 `03_api_reference.md`
- Kafka 消费与缓存流程细节：参见 `04_kafka_redis_flow.md`
- 故障涉及的实体关系：参见 `06_graph_relations.md`
