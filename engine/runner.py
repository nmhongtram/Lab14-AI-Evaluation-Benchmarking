"""
Async Benchmark Runner — Lab 14
Chạy song song toàn bộ test cases theo batch để tránh rate-limit.
"""
import asyncio
import time
from typing import List, Dict


class BenchmarkRunner:
    def __init__(self, agent, evaluator, judge):
        self.agent     = agent
        self.evaluator = evaluator
        self.judge     = judge

    async def run_single_test(self, test_case: Dict) -> Dict:
        start = time.perf_counter()

        # 1. Gọi Agent — truyền expected_retrieval_ids để simulate realistic retrieval
        expected_ids: List[str] = test_case.get("expected_retrieval_ids", [])
        response = await self.agent.query(test_case["question"], expected_ids)
        latency = time.perf_counter() - start

        # 2. Retrieval + RAGAS-proxy metrics
        ragas_scores = await self.evaluator.score(test_case, response)

        # 3. Multi-Judge (GPT-4o-mini + GPT-4o)
        judge_result = await self.judge.evaluate_multi_judge(
            test_case["question"],
            response["answer"],
            test_case["expected_answer"],
        )

        return {
            "id":            test_case.get("id", "unknown"),
            "test_case":     test_case["question"],
            "agent_response": response["answer"],
            "latency":       round(latency, 4),
            "ragas":         ragas_scores,
            "judge":         judge_result,
            "metadata":      test_case.get("metadata", {}),
            "status":        "fail" if judge_result["final_score"] < 3.0 else "pass",
        }

    async def run_all(
        self, dataset: List[Dict], batch_size: int = 5
    ) -> List[Dict]:
        """
        Chạy song song theo batch để tránh rate-limit.
        batch_size=5 là cân bằng tốt giữa tốc độ và an toàn API.
        """
        results: List[Dict] = []
        for i in range(0, len(dataset), batch_size):
            batch = dataset[i : i + batch_size]
            tasks = [self.run_single_test(case) for case in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
        return results
