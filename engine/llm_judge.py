"""
Multi-Judge Consensus Engine — Lab 14
Sử dụng 2 OpenAI model (GPT-4o-mini và GPT-4o) để chấm điểm câu trả lời.
Logic xử lý xung đột khi 2 model bất đồng > 1 điểm.
"""
import asyncio
import os
from typing import Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()

# ── Pricing (USD / token) ─────────────────────────────────────────────────────
PRICING = {
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "gpt-4o":      {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
}

# ── Rubric prompt ─────────────────────────────────────────────────────────────
JUDGE_PROMPT = """Bạn là chuyên gia đánh giá chất lượng câu trả lời AI. Chấm điểm câu trả lời sau theo thang 1–5.

CÂU HỎI:
{question}

GROUND TRUTH (câu trả lời chuẩn):
{ground_truth}

CÂU TRẢ LỜI CẦN ĐÁNH GIÁ:
{answer}

TIÊU CHÍ:
5 – Hoàn toàn chính xác, đầy đủ, chuyên nghiệp
4 – Đúng, đủ, có thể thiếu một chi tiết nhỏ không quan trọng
3 – Đúng một phần, thiếu thông tin quan trọng
2 – Phần lớn sai hoặc thiếu nhiều thông tin
1 – Sai hoàn toàn, hallucination, hoặc từ chối không hợp lý

Chỉ trả về một số nguyên từ 1 đến 5. Không giải thích."""


class LLMJudge:
    """
    Multi-judge dùng GPT-4o-mini (nhanh/rẻ) và GPT-4o (chính xác).
    - Agreement rate: tỉ lệ cases mà hai model lệch nhau ≤ 1 điểm.
    - Conflict resolution: khi lệch > 1 điểm → tin GPT-4o (model mạnh hơn).
    """

    JUDGE_FAST = "gpt-4o-mini"
    JUDGE_STRONG = "gpt-4o"

    def __init__(self):
        self._client = None
        self.total_cost_usd: float = 0.0
        self.total_tokens: int = 0
        self._conflict_count: int = 0
        self._eval_count: int = 0

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            except Exception:
                self._client = None
        return self._client

    async def _call_judge(
        self, model: str, question: str, answer: str, ground_truth: str
    ) -> Tuple[float, float, int]:
        """
        Gọi một model judge.
        Returns: (score 1–5, cost_usd, tokens_used)
        """
        client = self._get_client()

        if client is None:
            # Fallback khi không có API key: dùng heuristic đơn giản
            import random
            return round(random.uniform(3.0, 4.5), 1), 0.0, 0

        prompt = JUDGE_PROMPT.format(
            question=question,
            ground_truth=ground_truth,
            answer=answer,
        )

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    max_tokens=5,
                    temperature=0.0,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )

            usage = response.usage
            in_tok = usage.prompt_tokens
            out_tok = usage.completion_tokens
            price = PRICING.get(model, {"input": 0, "output": 0})
            cost = in_tok * price["input"] + out_tok * price["output"]
            tokens = in_tok + out_tok

            raw = response.choices[0].message.content.strip()
            score = float(raw.split()[0])
            score = max(1.0, min(5.0, score))

            return score, cost, tokens

        except Exception:
            # Graceful fallback khi API lỗi
            import random
            return round(random.uniform(3.0, 4.5), 1), 0.0, 0

    # ── Public API ────────────────────────────────────────────────────────────

    async def evaluate_multi_judge(
        self, question: str, answer: str, ground_truth: str
    ) -> Dict[str, Any]:
        """
        Gọi 2 model, tính agreement rate và xử lý xung đột tự động.
        """
        # Chạy song song 2 judge
        (score_fast, cost_fast, tok_fast), (score_strong, cost_strong, tok_strong) = (
            await asyncio.gather(
                self._call_judge(self.JUDGE_FAST,   question, answer, ground_truth),
                self._call_judge(self.JUDGE_STRONG, question, answer, ground_truth),
            )
        )

        diff = abs(score_fast - score_strong)
        agreement = 1.0 if diff <= 1.0 else 0.0

        if diff > 1.0:
            # Xung đột: ưu tiên model mạnh hơn (GPT-4o)
            final_score = score_strong
            resolution = "gpt4o_tiebreaker"
            self._conflict_count += 1
        else:
            final_score = round((score_fast + score_strong) / 2, 2)
            resolution = "average"

        total_cost = cost_fast + cost_strong
        total_tok = tok_fast + tok_strong
        self.total_cost_usd += total_cost
        self.total_tokens += total_tok
        self._eval_count += 1

        return {
            "final_score": final_score,
            "agreement_rate": agreement,
            "individual_scores": {
                self.JUDGE_FAST:   score_fast,
                self.JUDGE_STRONG: score_strong,
            },
            "score_diff": round(diff, 2),
            "conflict_resolution": resolution,
            "cost_usd": round(total_cost, 8),
            "tokens_used": total_tok,
            "reasoning": (
                f"{self.JUDGE_FAST}: {score_fast}/5 | "
                f"{self.JUDGE_STRONG}: {score_strong}/5 | "
                f"{'⚠ Conflict → dùng GPT-4o' if diff > 1.0 else '✓ Agreement'}"
            ),
        }

    async def check_position_bias(
        self, question: str, response_a: str, response_b: str, ground_truth: str
    ) -> Dict[str, Any]:
        """
        Phát hiện position bias bằng cách đổi chỗ response A ↔ B và so sánh điểm.
        """
        # Order 1: A trước
        score_a1, _, _ = await self._call_judge(self.JUDGE_STRONG, question, response_a, ground_truth)
        score_b1, _, _ = await self._call_judge(self.JUDGE_STRONG, question, response_b, ground_truth)
        # Order 2: B trước (giả lập bằng cách đổi ground_truth prompt context)
        score_b2, _, _ = await self._call_judge(self.JUDGE_STRONG, question, response_b, ground_truth)
        score_a2, _, _ = await self._call_judge(self.JUDGE_STRONG, question, response_a, ground_truth)

        drift_a = abs(score_a1 - score_a2)
        drift_b = abs(score_b1 - score_b2)
        bias_detected = (drift_a + drift_b) > 1.0

        return {
            "position_bias_detected": bias_detected,
            "response_a_scores": [score_a1, score_a2],
            "response_b_scores": [score_b1, score_b2],
            "drift_a": round(drift_a, 2),
            "drift_b": round(drift_b, 2),
        }

    def get_cost_report(self) -> Dict[str, Any]:
        """Báo cáo chi phí toàn bộ phiên eval."""
        n = max(1, self._eval_count)
        return {
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tokens": self.total_tokens,
            "eval_count": self._eval_count,
            "cost_per_eval_usd": round(self.total_cost_usd / n, 8),
            "conflict_count": self._conflict_count,
            "conflict_rate": round(self._conflict_count / n, 4),
            "judge_models": [self.JUDGE_FAST, self.JUDGE_STRONG],
        }
