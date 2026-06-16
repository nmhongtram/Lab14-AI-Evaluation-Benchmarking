"""
Main Agent — Lab 14
Mô phỏng RAG pipeline với retrieval không hoàn hảo để tạo dữ liệu benchmark thực tế.
V1 (hit_rate_target=0.72) và V2 (hit_rate_target=0.88) cho regression testing.
"""
import asyncio
import random
from typing import Dict, List


ALL_DOC_IDS = [f"DOC_{i:03d}" for i in range(1, 11)]


class MainAgent:
    """
    Agent V1: baseline với retrieval ~72% hit rate.
    Mô phỏng lỗi thực tế: đôi khi lấy nhầm document, đôi khi bỏ sót.
    """

    def __init__(self, hit_rate_target: float = 0.72, name: str = "SupportAgent-v1"):
        self.name = name
        self.hit_rate_target = hit_rate_target

    def _simulate_retrieval(self, expected_ids: List[str]) -> List[str]:
        """
        Mô phỏng vector search không hoàn hảo:
        - Với xác suất hit_rate_target: lấy đúng document
        - Thêm noise (document nhiễu) để HitRate < 1.0
        - Out-of-context (expected_ids rỗng): trả về list rỗng
        """
        if not expected_ids:
            # Agent tốt nên biết "không tìm thấy gì liên quan"
            return [] if random.random() < 0.8 else [random.choice(ALL_DOC_IDS)]

        retrieved: List[str] = []

        # Thử lấy từng expected doc
        for doc_id in expected_ids:
            if random.random() < self.hit_rate_target:
                retrieved.append(doc_id)

        # Thêm noise doc (sai)
        noise_pool = [d for d in ALL_DOC_IDS if d not in expected_ids]
        n_noise = random.randint(0, 2)
        if noise_pool and n_noise:
            retrieved += random.sample(noise_pool, min(n_noise, len(noise_pool)))

        random.shuffle(retrieved)
        return retrieved[:3]  # top-3 retrieved

    async def query(
        self, question: str, expected_retrieval_ids: List[str] = None
    ) -> Dict:
        if expected_retrieval_ids is None:
            expected_retrieval_ids = []

        # Mô phỏng latency LLM (50-150ms)
        await asyncio.sleep(random.uniform(0.05, 0.15))

        retrieved_ids = self._simulate_retrieval(expected_retrieval_ids)

        return {
            "answer": (
                f"Dựa trên tài liệu nội bộ TechCorp (nguồn: {', '.join(retrieved_ids) or 'N/A'}), "
                f"câu trả lời cho câu hỏi '{question[:60]}...' là: [Câu trả lời được tổng hợp từ context đã truy xuất]."
            ),
            "contexts": [
                f"[{doc_id}] Thông tin liên quan đến chủ đề câu hỏi..."
                for doc_id in retrieved_ids
            ],
            "retrieved_ids": retrieved_ids,
            "metadata": {
                "model": "gpt-4o-mini",
                "tokens_used": random.randint(80, 250),
                "sources": retrieved_ids,
                "agent_version": self.name,
            },
        }


class MainAgentV2(MainAgent):
    """
    Agent V2: phiên bản tối ưu với retrieval ~88% hit rate.
    Dùng cho regression testing (so sánh V1 vs V2).
    """

    def __init__(self):
        super().__init__(hit_rate_target=0.88, name="SupportAgent-v2")


# ── Quick smoke test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        agent = MainAgent()
        resp = await agent.query(
            "Nhân viên được nghỉ phép bao nhiêu ngày?",
            expected_retrieval_ids=["DOC_001"],
        )
        print("Agent V1:", resp)

        agent_v2 = MainAgentV2()
        resp2 = await agent_v2.query(
            "Mật khẩu cần bao nhiêu ký tự?",
            expected_retrieval_ids=["DOC_002"],
        )
        print("Agent V2:", resp2)

    asyncio.run(_test())
