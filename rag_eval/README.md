# LightRAG 查询模式自动评测

这个目录提供一个独立评测流程，用于比较 `naive`、`local`、`global`、`hybrid`、`mix`
在同一批问题上的表现差异。脚本优先使用 LightRAG HTTP API：

- `POST /query`：获取生成答案。
- `POST /query/data`：获取结构化检索上下文，包括 `entities`、`relationships`、`chunks`、`references`。

## 1. 生成问题

```bash
python3 -m rag_eval.generate_questions \
  --num-questions 30 \
  --output-dir outputs \
  --source-doc "诡秘之主(501-1000章).txt"
```

输出：`outputs/questions.json`。

## 2. 执行多模式查询

```bash
python3 -m rag_eval.run_queries \
  --endpoint http://10.12.222.57:9621 \
  --modes naive,local,global,hybrid,mix \
  --num-questions 30 \
  --output-dir outputs \
  --concurrency 1 \
  --sleep 0.5 \
  --resume
```

如果服务启用了 API Key：

```bash
export LIGHTRAG_API_KEY="..."
```

或者：

```bash
export RAG_EVAL_HEADERS_JSON='{"Authorization":"Bearer ..."}'
```

输出：

- `outputs/results.jsonl`
- `outputs/results.csv`

`--resume` 会跳过已有的 `question_id + query_mode` 组合。

## 3. 评分

默认规则评分：

```bash
python3 -m rag_eval.evaluate_results --output-dir outputs --judge rule
```

可选 LLM Judge：

```bash
export RAG_EVAL_JUDGE_ENDPOINT="https://api.example.com/v1"
export RAG_EVAL_JUDGE_API_KEY="..."
export RAG_EVAL_JUDGE_MODEL="deepseek-chat"
python3 -m rag_eval.evaluate_results --output-dir outputs --judge llm
```

输出：`outputs/scored_results.jsonl`，并刷新 `outputs/results.csv`。

## 4. 生成报告

```bash
python3 -m rag_eval.build_report --output-dir outputs
```

输出：`outputs/report.md`。

## 5. 一次完整运行

```bash
python3 -m rag_eval.generate_questions --num-questions 30 --output-dir outputs
python3 -m rag_eval.run_queries --endpoint http://10.12.222.57:9621 --resume
python3 -m rag_eval.evaluate_results --output-dir outputs --judge rule
python3 -m rag_eval.build_report --output-dir outputs
```

## 评分维度

每条答案按 7 个维度评分，每项 0-5 分：

- `relevance_score`
- `factual_grounding_score`
- `relation_score`
- `causal_score`
- `boundary_score`
- `structure_score`
- `completeness_score`

额外标记包括：

- `possible_timeline_leak`
- `too_broad`
- `too_shallow`
- `missing_evidence`
- `entity_confusion`
- `mode_error`
- `over_retrieval`
- `under_retrieval`

规则评分是初筛，不替代人工复核。尤其是时间线泄漏、实体混淆和“答案丰富但边界错误”的案例，应优先人工检查。
