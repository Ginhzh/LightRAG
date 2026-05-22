# 普通 RAG vs Graph-RAG 评分表

## 评估说明

- 本表用于评估同一批问题在普通 RAG 与 Graph-as-Text + RAG 两种方案下的答案质量。

- 评分由 DeepSeek API 基于题目、期望关键词/答案要点、两版答案和 sources 列表自动生成。

- 评分标准：0=错误或没有回答；1=部分正确但遗漏严重；2=基本正确但解释不完整；3=正确、完整、有依据；4=正确、完整、有关系链、有明确排查建议或可执行判断路径。

- “是否包含关系链”分别判断普通 RAG 和 Graph-RAG 是否明确描述实体、接口、表、缓存、错误之间的链式关系。

- “是否引用正确来源”关注答案引用与 sources 是否相关；sources 为空或引用无法支撑答案时记为否。

- “是否出现幻觉”指答案中是否有与期望要点或给定来源明显冲突、无法支撑的具体断言。


## 空白评分模板

| 问题编号 | 问题 | 问题类型 | 普通 RAG 答案评分 | Graph-RAG 答案评分 | 准确性对比 | 完整性对比 | 是否包含关系链 | 是否引用正确来源 | 是否出现幻觉 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  | 0-4 | 0-4 |  |  | 普通: 是/否；Graph: 是/否 | 普通: 是/否；Graph: 是/否 | 普通: 有/无；Graph: 有/无 |  |


## 自动评分汇总

- 总题数：50

- 普通 RAG 平均分：2.18

- Graph-RAG 平均分：2.56

- Graph-RAG 更优：21

- 普通 RAG 更优：3

- 打平：26


## 自动评分明细

| 问题编号 | 问题 | 问题类型 | 普通 RAG 答案评分 | Graph-RAG 答案评分 | 准确性对比 | 完整性对比 | 是否包含关系链 | 是否引用正确来源 | 是否出现幻觉 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | EPC2 通过 Kafka 推送的入库消息主要是什么类型的业务数据？ | 事实型 | 3 | 3 | 两者均正确指出是文档元数据/DOC_INGEST消息，准确度一致 | 两者均完整，RAG额外提及FILE_ADD等类型，Graph-RAG更详细列出元数据字段，完整性相当 | 普通: 否；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平，两者均正确完整 |
| 2 | knowledge-service 在这条链路中的职责是什么？ | 事实型 | 3 | 4 | 两者均正确描述职责，Graph-RAG更详细准确 | Graph-RAG更完整，包含消息消费、校验、入库、日志记录、缓存清理、重放跳过等全部环节 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优，更完整且有关系链 |
| 3 | unstructured_documents 表的唯一键 uq_sys_filenum 由哪些字段组成？ | 事实型 | 3 | 3 | 两者均正确指出由system_name和file_id组成，准确度一致 | 两者均完整，直接给出答案，完整性相当 | 普通: 否；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平，两者均正确完整 |
| 4 | repo_mappings 表主要维护什么映射关系？ | 事实型 | 2 | 4 | 两者均正确指出systemName+repoId映射，Graph-RAG更准确 | Graph-RAG更完整，详细说明校验逻辑、读取方及缓存关系 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优，更完整且有关系链 |
| 5 | kafka_message_logs 表记录的核心内容是什么？ | 事实型 | 3 | 4 | 两者均正确指出记录处理结果和可追溯性，Graph-RAG更准确 | Graph-RAG更完整，详细列出字段、状态码及重放接口依赖 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优，更完整且有关系链 |
| 6 | zhenzhi-adapter 的 /api/kafka-replay/today 接口是做什么的？ | 事实型 | 3 | 3 | 两者均准确描述了接口功能 | 两者均完整，Graph-RAG 额外提到了必填参数 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 7 | zhenzhi-adapter 的 /api/cache/redis/all 接口是做什么的？ | 事实型 | 3 | 3 | 两者均准确描述了接口功能 | 两者均完整，Graph-RAG 额外提到了影响 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 8 | zhenzhi-adapter 的 /api/v1/statistics/redis/system-daily 接口是做什么的？ | 事实型 | 1 | 1 | 两者均无法确认接口功能 | 两者均未提供有效信息 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平 |
| 9 | Redis 在这个业务场景里主要缓存哪几类数据？ | 事实型 | 2 | 0 | RAG 答案与期望要点一致，Graph-RAG 答案与期望要点不符 | RAG 答案覆盖了文件状态和每日统计，Graph-RAG 答案完全错误 | 普通: 是；Graph: 否 | 普通: 是；Graph: 否 | 普通: 无；Graph: 有 | RAG 更优 |
| 10 | system_name 在这个场景里出现在哪些核心位置？ | 事实型 | 0 | 0 | 两者均无法回答 | 两者均未提供有效信息 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平 |
| 11 | file_id 在这个场景里最关键的作用是什么？ | 事实型 | 3 | 4 | 两者均正确，Graph-RAG 更详细 | Graph-RAG 补充了冲突处理策略，更完整 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG 更优 |
| 12 | 哪一个组件对外提供 Kafka 重放和 Redis 查询相关接口？ | 事实型 | 3 | 4 | 两者均正确，Graph-RAG 更详细 |  | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG 更优 |
| 13 | knowledge-service 写入的目标表是哪一张？ | 事实型 | 2 | 3 | RAG 多写了 kafka_message_logs，不准确；Graph-RAG 正确 | Graph-RAG 更准确，RAG 有冗余信息 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 有；Graph: 无 | Graph-RAG 更优 |
| 14 | repo_id 在 repo_mappings 里代表什么？ | 事实型 | 3 | 4 | 两者均正确，Graph-RAG 更详细 | Graph-RAG 补充了映射关系和修复方法，更完整 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG 更优 |
| 15 | Redis 里保存的文件处理状态通常用于什么？ | 事实型 | 2 | 2 | 两者均正确，但都较笼统 | 两者均未提及快速查询和故障定位，完整性不足 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平 |
| 16 | EPC2、Kafka、knowledge-service、unstructured_documents 这条链路之间是什么关系？ | 关系型 | 3 | 3 | 两者均正确描述了链路关系 | 两者均完整，Graph-RAG 额外提及了其他写入表 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平，两者均正确完整 |
| 17 | system_name 这个字段和哪些表存在直接关系？ | 关系型 | 1 | 1 | 两者均只提到 repo_mappings，遗漏 unstructured_documents | 两者均不完整，未提及与 unstructured_documents 的关系 | 普通: 否；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平，两者均部分正确但遗漏严重 |
| 18 | file_id 这个字段和哪些数据对象有关？ | 关系型 | 0 | 0 | 两者均无法确认 | 两者均未回答 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平，两者均未回答 |
| 19 | Redis 缓存与哪些接口直接相关？ | 关系型 | 2 | 2 | 两者均正确提及了相关接口 | 两者均只提到两个接口，但期望要点中还有 /api/v1/statistics/redis/system-daily 未提及 | 普通: 否；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平，两者均基本正确但解释不完整 |
| 20 | Kafka 重放和哪些表、接口、日志会形成联动？ | 关系型 | 3 | 3 | 两者均正确描述了联动关系 | 两者均完整，Graph-RAG 额外提及了回调接口 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平，两者均正确完整 |
| 21 | repo_mappings 和 unstructured_documents 在写入链路里是什么关系？ | 关系型 | 3 | 1 | 普通RAG准确描述了前置校验关系，Graph-RAG错误地认为无直接关系 | 普通RAG完整描述了写入链路中的前置校验关系，Graph-RAG未提供有效信息 | 普通: 是；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 普通RAG更优 |
| 22 | kafka_message_logs 和 Redis 文件处理状态之间是什么关系？ | 关系型 | 3 | 4 | 两者都准确描述了间接关联关系 | Graph-RAG更完整地描述了重放流程和缓存回源机制，普通RAG也较完整 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 23 | 系统每日统计和哪条接口、哪种缓存关系最直接？ | 关系型 | 2 | 3 | 两者都准确，但Graph-RAG更具体地描述了接口和缓存的关系 | Graph-RAG更完整地描述了接口、缓存和数据库之间的链式关系，普通RAG仅提及接口和缓存 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 24 | 接口查询结果缓存通常对应哪些查询接口？ | 关系型 | 2 | 1 | 普通RAG准确描述了缓存对应的接口，Graph-RAG仅提及两个接口名称但不够具体 | 普通RAG更完整地描述了缓存机制和对应接口，Graph-RAG信息不足 | 普通: 是；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 普通RAG更优 |
| 25 | 为什么 system_name 既和 repo_mappings 有关，也和唯一键有关？ | 关系型 | 3 | 4 | 两者都准确描述了system_name的双重角色 | Graph-RAG更完整地说明了两个唯一键的具体字段和业务目的，普通RAG也较完整 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 26 | 为什么 file_id 在这个场景中不能单独作为唯一标识？ | 关系型 | 3 | 3 | 两者均正确，无差异 | 两者均完整，无差异 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 27 | Kafka 消息、日志表、入库表三者是什么关系？ | 关系型 | 1 | 3 | Graph-RAG 准确描述了关系，普通 RAG 未完整回答 | Graph-RAG 完整，普通 RAG 遗漏关键点 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG 更优 |
| 28 | zhenzhi-adapter 的三个接口分别和哪些数据层相关？ | 关系型 | 2 | 3 | Graph-RAG 更准确，普通 RAG 未明确对应具体接口 | Graph-RAG 更完整，普通 RAG 遗漏接口细节 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG 更优 |
| 29 | 同一个 system_name 可能同时关联哪些对象？ | 关系型 | 0 | 0 | 两者均无法回答 | 两者均未提供有效信息 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平 |
| 30 | 文件处理状态、消息处理状态、最终入库结果之间是什么关系？ | 关系型 | 0 | 0 | 两者均无法回答 | 两者均未提供有效信息 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平 |
| 31 | 如果从接口层看，这套系统有哪些查询入口？ | 关系型 | 0 | 0 | 两者均未给出具体查询入口，均错误 | 两者均未提供任何具体接口，均不完整 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平，均得0分 |
| 32 | 为什么 /api/kafka-replay/today 重放今天的消息后，可能出现 Duplicate entry 错误？ | 多跳推理 | 3 | 3 | 两者均正确解释了重放导致唯一键冲突的原因 | 两者均完整覆盖了重放机制、消费逻辑和唯一键约束 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平，均得3分 |
| 33 | 如果 kafka_message_logs 显示处理成功，但 unstructured_documents 没有对应记录，最可能说明什么？ | 多跳推理 | 2 | 3 | 两者均正确指出唯一键冲突导致跳过，但Graph-RAG额外提到仓库禁用场景 | Graph-RAG更完整，包含了跳过状态和仓库禁用两种可能 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 34 | 如果 Redis 里显示文件已处理，但数据库里查不到文档，应该如何理解？ | 多跳推理 | 0 | 0 | 两者均无法确认，均错误 | 两者均未提供有效解释，均不完整 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平，均得0分 |
| 35 | 如果 repo_mappings 里缺少某个 system_name，会对入库链路造成什么影响？ | 多跳推理 | 3 | 4 | 两者均正确指出缺少映射导致跳过 | Graph-RAG更完整，包含了校验失败、消息跳过和无法自动恢复的完整链路及排查建议 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 36 | 为什么同一个 file_id 在不同 system_name 下不一定算重复？ | 多跳推理 | 3 | 3 | 两者均正确解释了唯一键组成，准确性相同 | 两者均完整解释了唯一键约束，完整性相同 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 37 | 为什么系统每日统计在重放后可能变大，但实际文档数没有同步增加？ | 多跳推理 | 1 | 1 | 两者均未准确指出统计缓存累计重放次数和文档表因重复键未新增的核心原因 | 两者均只给出泛化解释，未覆盖期望要点 | 普通: 否；Graph: 否 | 普通: 否；Graph: 否 | 普通: 无；Graph: 无 | 打平 |
| 38 | 为什么 /api/cache/redis/all 和数据库结果不一致时，不能直接相信缓存？ | 多跳推理 | 4 | 4 | 两者均准确指出缓存不一致的根本原因是Redis清除失败，准确性相同 | 两者均完整解释了原因并给出排查建议，完整性相同 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 39 | 为什么 Kafka 消息重试次数变多时，更容易遇到重复入库？ | 多跳推理 | 1 | 2 | RAG未能解释因果关系，Graph-RAG正确指出了重试与幂等性冲突的关联 | RAG缺少关键推理，Graph-RAG较完整地解释了重试导致重复入库的机制 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 40 | repo_mappings 和 unstructured_documents 如何共同解释“同系统同文件只能入一条”这一事实？ | 多跳推理 | 3 | 4 | 两者均正确解释了唯一键和映射校验的作用 | Graph-RAG更完整地描述了多跳关系，包括实体和约束的链式关系 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 41 | 为什么 kafka_message_logs 是定位重复写入问题的重要线索？ | 多跳推理 | 2 | 2 | 两者均正确，但都未提及对比第一次和重放时的处理状态 | 两者均不完整，缺少期望要点中的对比第一次和重放时的处理状态 | 普通: 否；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平，两者均不完整 |
| 42 | 如果 /api/kafka-replay/today 返回成功，但 /api/v1/statistics/redis/system-daily 没有变化，可能是什么原因？ | 多跳推理 | 3 | 4 | 两者均正确，Graph-RAG 更详细 | Graph-RAG 更完整，额外提到了缓存 Key 模式不匹配 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG 更优 |
| 43 | 如果某个 system_name 的入库总是失败，但别的 system_name 正常，如何从表关系上推断原因？ | 多跳推理 | 3 | 3 | 两者均正确，内容基本一致 | 两者均完整，覆盖了期望要点 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 44 | 为什么同一条 Kafka 消息在日志里有记录，但文件状态缓存和统计缓存都没更新，仍可能是链路问题？ | 多跳推理 | 2 | 4 | 两者均正确，Graph-RAG 更聚焦于链路 | Graph-RAG 更完整，明确描述了消费链路和缓存失效步骤 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG 更优 |
| 45 | 为什么在排查重复入库时，必须同时看 system_name 和 file_id？ | 多跳推理 | 3 | 3 | 两者均正确，内容基本一致 | 两者均完整，覆盖了期望要点 | 普通: 否；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 46 | 如果 Redis 里接口查询结果是旧的，而 Kafka 消息已经重放过，应该如何推断？ | 多跳推理 | 3 | 3 | 两者均正确推断出Redis缓存未更新和Kafka重放可能被跳过，准确性相当。 | 两者均完整覆盖了缓存未更新、重放跳过、排查步骤等要点，完整性相当。 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 47 | 看到 Duplicate entry for key uq_sys_filenum 时，第一步应该查什么？ | 故障排查 | 2 | 2 | 两者均正确指出第一步应查询已存在记录，准确性相当。 | 两者均只给出了第一步查询，未提及第二步查kafka_message_logs，完整性相当。 | 普通: 否；Graph: 否 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | 打平 |
| 48 | /api/kafka-replay/today 返回成功，但新文档没进库，应该查哪些地方？ | 故障排查 | 3 | 4 | 两者均正确指出需检查kafka_message_logs、唯一键冲突等，Graph-RAG额外提及了repo_mappings映射检查，更准确。 | Graph-RAG覆盖了更多排查点（如消费端、映射校验），更完整。 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 49 | /api/cache/redis/all 显示文件已处理，但业务侧说文档缺失，应该怎么排查？ | 故障排查 | 3 | 4 | 两者均正确指出接口仅清理缓存，需查数据库。Graph-RAG额外解释了缓存空值标记导致的问题，更准确。 | Graph-RAG覆盖了缓存空值、唯一键冲突等更多细节，更完整。 | 普通: 是；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
| 50 | 系统每日统计异常偏高时，应该优先检查哪些表和接口？ | 故障排查 | 1 | 2 | RAG回答过于泛化，未针对具体系统；Graph-RAG正确指向了unstructured_documents表和统计接口，更准确。 | Graph-RAG覆盖了表、接口、缓存三个关键点，更完整。 | 普通: 否；Graph: 是 | 普通: 是；Graph: 是 | 普通: 无；Graph: 无 | Graph-RAG更优 |
