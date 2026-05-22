# RAG / Graph-RAG 简单问答智能体

这个脚本做一条最小链路：

1. 调用知识库检索接口拿上下文
2. 把检索结果拼成上下文
3. 调用 DeepSeek 兼容模型生成答案

脚本位置：

```bash
rag_test/scripts/rag_qa_agent.py
```


## 依赖环境

脚本会自动读取仓库根目录 `.env`，重点变量是：

```bash
EXTERNAL_RAG_URL=...
EXTERNAL_RAG_HEADERS_JSON=...
OPENAI_API_KEY=...
OPENAI_API_BASE=https://api.deepseek.com/v1
```

也兼容：

```bash
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-chat
```

如果 `OPENAI_API_BASE` 没带 `/v1`，脚本会自动补上。
脚本通过 `requests` 直接调用：

- 知识库检索接口 `EXTERNAL_RAG_URL`
- DeepSeek 兼容接口 `/chat/completions`


## 用法

普通 RAG 模式：

```bash
python3 rag_test/scripts/rag_qa_agent.py --mode rag "Kafka 重放为什么可能导致 Duplicate entry？"
```

Graph-RAG 倾向模式：

```bash
python3 rag_test/scripts/rag_qa_agent.py --mode graph "Kafka 重放为什么可能导致 Duplicate entry？"
```

打印检索上下文：

```bash
python3 rag_test/scripts/rag_qa_agent.py --mode graph --show-context "repo_mappings 和 unstructured_documents 有什么关系？"
```

输出 JSON：

```bash
python3 rag_test/scripts/rag_qa_agent.py --json "接口查询结果为什么可能和数据库不一致？"
```


## 设计说明

- 检索和生成是分离的。
- 图关系不是手工拼进 prompt 的，而是作为知识库文档被检索出来。
- `graph` 模式只改变回答提示词，不改检索接口，便于和普通 RAG 做对照实验。
