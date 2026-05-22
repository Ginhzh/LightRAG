from __future__ import annotations

import asyncio
import io
import json
import sys
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_baseline


class FakeRAG:
    def __init__(self) -> None:
        self.aquery_data_calls = []
        self.aquery_llm_calls = []

    async def aquery_data(self, question, param):
        self.aquery_data_calls.append((question, param))
        return {
            "status": "success",
            "data": {
                "chunks": [
                    {
                        "chunk_id": "chunk-1",
                        "content": "结构化上下文不应作为 baseline 答案。",
                    }
                ]
            },
        }

    async def aquery_llm(self, question, param):
        self.aquery_llm_calls.append((question, param))
        return {
            "status": "success",
            "data": {"chunks": [{"chunk_id": "chunk-1"}]},
            "llm_response": {
                "content": "这是可评分的 baseline 答案。",
                "response_iterator": None,
                "is_streaming": False,
            },
        }


class RunBaselineTests(unittest.TestCase):
    def test_main_async_uses_llm_answer_not_context_only_data(self) -> None:
        fake_rag = FakeRAG()

        @asynccontextmanager
        async def fake_create_rag():
            yield fake_rag

        original_create_rag = run_baseline.create_rag
        run_baseline.create_rag = fake_create_rag
        stdout = io.StringIO()
        try:
            with redirect_stdout(stdout):
                asyncio.run(run_baseline.main_async("问题", "mix"))
        finally:
            run_baseline.create_rag = original_create_rag

        payload = json.loads(stdout.getvalue())

        self.assertEqual(len(fake_rag.aquery_llm_calls), 1)
        self.assertEqual(fake_rag.aquery_data_calls, [])
        self.assertEqual(payload["llm_response"]["content"], "这是可评分的 baseline 答案。")
        self.assertEqual(fake_rag.aquery_llm_calls[0][1].mode, "mix")
        self.assertFalse(fake_rag.aquery_llm_calls[0][1].stream)


if __name__ == "__main__":
    unittest.main()
