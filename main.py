"""
Lab 14 — AI Evaluation Factory
Chạy: python main.py
Pipeline: SDG → Benchmark (V1 & V2) → Regression Gate → Reports
"""
import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Tuple

from agent.main_agent import MainAgent, MainAgentV2
from engine.llm_judge import LLMJudge
from engine.retrieval_eval import RetrievalEvaluator
from engine.runner import BenchmarkRunner

# ── Release Gate thresholds ───────────────────────────────────────────────────
GATE = {
    "min_avg_score":      3.5,   # điểm judge tối thiểu
    "min_hit_rate":       0.60,  # retrieval hit rate tối thiểu
    "min_agreement_rate": 0.70,  # đồng thuận 2 judge tối thiểu
    "max_score_drop":    -0.20,  # cho phép giảm tối đa 0.2 điểm so với V1
}


# ── Core benchmark function ───────────────────────────────────────────────────

async def run_benchmark(
    version: str,
    agent,
    dataset: List[Dict],
    judge: LLMJudge,
) -> Tuple[Optional[List[Dict]], Optional[Dict]]:

    print(f"\n{'─'*55}")
    print(f"  Chạy benchmark: {version}")
    print(f"{'─'*55}")

    evaluator = RetrievalEvaluator()
    runner    = BenchmarkRunner(agent, evaluator, judge)

    t0 = time.perf_counter()
    results = await runner.run_all(dataset, batch_size=5)
    elapsed = time.perf_counter() - t0

    total  = len(results)
    passes = sum(1 for r in results if r["status"] == "pass")

    # ── Aggregate metrics ─────────────────────────────────────────────────────
    avg_score      = sum(r["judge"]["final_score"]   for r in results) / total
    agreement_rate = sum(r["judge"]["agreement_rate"] for r in results) / total
    faithfulness   = sum(r["ragas"]["faithfulness"]  for r in results) / total
    relevancy      = sum(r["ragas"]["relevancy"]     for r in results) / total

    # Retrieval chỉ tính trên các case có expected_retrieval_ids
    ret_cases = [r for r in results if r["ragas"]["retrieval"]["expected_ids"]]
    hit_rate  = (sum(r["ragas"]["retrieval"]["hit_rate"] for r in ret_cases) / len(ret_cases)
                 if ret_cases else 0.0)
    mrr       = (sum(r["ragas"]["retrieval"]["mrr"] for r in ret_cases) / len(ret_cases)
                 if ret_cases else 0.0)

    total_cost   = sum(r["judge"].get("cost_usd", 0)     for r in results)
    total_tokens = sum(r["judge"].get("tokens_used", 0)   for r in results)

    summary = {
        "metadata": {
            "version":         version,
            "total":           total,
            "passes":          passes,
            "fails":           total - passes,
            "pass_rate":       round(passes / total, 3),
            "elapsed_seconds": round(elapsed, 2),
            "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "metrics": {
            "avg_score":      round(avg_score, 3),
            "hit_rate":       round(hit_rate, 3),
            "mrr":            round(mrr, 4),
            "agreement_rate": round(agreement_rate, 3),
            "faithfulness":   round(faithfulness, 3),
            "relevancy":      round(relevancy, 3),
        },
        "cost": {
            "total_usd":      round(total_cost, 6),
            "total_tokens":   total_tokens,
            "cost_per_case":  round(total_cost / total, 8) if total else 0,
        },
    }

    print(f"  ✓ {total} cases | {elapsed:.1f}s | Pass: {passes}/{total} ({passes/total:.0%})")
    print(f"  Score: {avg_score:.3f}  HitRate: {hit_rate:.1%}  MRR: {mrr:.3f}")
    print(f"  Agreement: {agreement_rate:.1%}  Cost: ${total_cost:.4f}  Tokens: {total_tokens}")

    return results, summary


# ── Release Gate ──────────────────────────────────────────────────────────────

def apply_release_gate(v1_summary: Dict, v2_summary: Dict) -> Dict:
    m1 = v1_summary["metrics"]
    m2 = v2_summary["metrics"]
    delta = round(m2["avg_score"] - m1["avg_score"], 3)

    checks = {
        "avg_score >= threshold":
            m2["avg_score"] >= GATE["min_avg_score"],
        "hit_rate >= threshold":
            m2["hit_rate"] >= GATE["min_hit_rate"],
        "agreement_rate >= threshold":
            m2["agreement_rate"] >= GATE["min_agreement_rate"],
        "no_score_regression":
            delta >= GATE["max_score_drop"],
    }

    decision = "APPROVE" if all(checks.values()) else "BLOCK"

    return {
        "decision":   decision,
        "delta_score": delta,
        "v1_metrics": m1,
        "v2_metrics": m2,
        "checks":     checks,
        "thresholds": GATE,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    # 0. Kiểm tra dataset
    if not os.path.exists("data/golden_set.jsonl"):
        print("❌ Thiếu data/golden_set.jsonl. Chạy: python data/synthetic_gen.py")
        return

    with open("data/golden_set.jsonl", "r", encoding="utf-8") as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    if not dataset:
        print("❌ data/golden_set.jsonl rỗng.")
        return

    print(f"📂 Dataset: {len(dataset)} test cases")

    # Dùng chung một judge instance để tích lũy cost report
    judge = LLMJudge()

    # 1. Benchmark V1 (baseline)
    _, v1_summary = await run_benchmark(
        "Agent_V1_Base", MainAgent(), dataset, judge
    )
    if not v1_summary:
        return

    # 2. Benchmark V2 (optimized)
    v2_results, v2_summary = await run_benchmark(
        "Agent_V2_Optimized", MainAgentV2(), dataset, judge
    )
    if not v2_summary:
        return

    # 3. Regression Gate
    gate = apply_release_gate(v1_summary, v2_summary)

    # 4. In kết quả
    print(f"\n{'='*55}")
    print("  REGRESSION TESTING — KẾT QUẢ SO SÁNH")
    print(f"{'='*55}")
    print(f"  {'Metric':<22} {'V1':>8} {'V2':>8} {'Delta':>8}")
    print(f"  {'-'*50}")
    for key in ("avg_score", "hit_rate", "mrr", "agreement_rate"):
        v1v = gate["v1_metrics"][key]
        v2v = gate["v2_metrics"][key]
        d   = v2v - v1v
        print(f"  {key:<22} {v1v:>8.3f} {v2v:>8.3f} {d:>+8.3f}")

    print(f"\n  Release Gate Checks:")
    for check, passed in gate["checks"].items():
        icon = "✅" if passed else "❌"
        print(f"    {icon} {check}")

    verdict = gate["decision"]
    if verdict == "APPROVE":
        print(f"\n  ✅ QUYẾT ĐỊNH: CHẤP NHẬN BẢN CẬP NHẬT (APPROVE)")
    else:
        print(f"\n  ❌ QUYẾT ĐỊNH: TỪ CHỐI PHÁT HÀNH (BLOCK RELEASE)")

    # Cost report
    cost_report = judge.get_cost_report()
    print(f"\n  💰 Cost Report:")
    print(f"    Total cost   : ${cost_report['total_cost_usd']:.6f}")
    print(f"    Total tokens : {cost_report['total_tokens']:,}")
    print(f"    Cost/eval    : ${cost_report['cost_per_eval_usd']:.8f}")
    print(f"    Conflicts    : {cost_report['conflict_count']} ({cost_report['conflict_rate']:.1%})")

    # 5. Lưu reports
    os.makedirs("reports", exist_ok=True)

    final_summary = {
        **v2_summary,
        "regression": gate,
        "judge_cost_report": cost_report,
    }

    with open("reports/summary.json", "w", encoding="utf-8") as f:
        json.dump(final_summary, f, ensure_ascii=False, indent=2)

    with open("reports/benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(v2_results, f, ensure_ascii=False, indent=2)

    print(f"\n  📁 reports/summary.json & benchmark_results.json đã được lưu.")


if __name__ == "__main__":
    asyncio.run(main())
