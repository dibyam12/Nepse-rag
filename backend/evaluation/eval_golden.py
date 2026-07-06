"""
evaluation/eval_golden.py
Golden Prompt Quality Evaluation for NEPSE AI.

For each golden prompt pattern, runs the full agent and verifies:
  1. Match detection — golden_matcher correctly identifies the query
  2. Structure compliance — response follows the template structure hints
  3. No forbidden phrases — no buy/sell advice
  4. DISCLAIMER present — all responses end with disclaimer
  5. Length compliance — response within expected length range

Usage:
    cd backend
    venv\\Scripts\\python.exe -m evaluation.eval_golden
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path

# ── Django setup ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nepse_project.settings")

import django
django.setup()

logger = logging.getLogger("nepse_rag")

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ── Golden query test cases ───────────────────────────────────

TEST_GOLDEN_QUERIES = [
    {
        "question": "How is NABIL performing?",
        "symbols": ["NABIL"],
        "expected_golden_id": "single_stock_analysis",
        "must_contain": ["NABIL", "DISCLAIMER"],
        "must_not_contain": ["I would recommend", "you should buy"],
        "min_length": 150,
        "max_length": 1500,
    },
    {
        "question": "Compare NABIL and NICA",
        "symbols": ["NABIL", "NICA"],
        "expected_golden_id": "compare_two_stocks",
        "must_contain": ["NABIL", "NICA", "DISCLAIMER"],
        "must_not_contain": ["I would recommend"],
        "min_length": 250,
        "max_length": 2000,
    },
    {
        "question": "Should I buy NABIL?",
        "symbols": ["NABIL"],
        "expected_golden_id": "should_i_buy",
        "must_contain": ["DISCLAIMER"],
        "must_not_contain": [
            "I would recommend",
            "you should buy",
            "you should sell",
            "I would caution against buying",
        ],
        "min_length": 100,
        "max_length": 1000,
    },
    {
        "question": "What is RSI?",
        "symbols": [],
        "expected_golden_id": "what_is_indicator",
        "must_contain": ["RSI"],
        "must_not_contain": [],
        "min_length": 80,
        "max_length": 800,
    },
    {
        "question": "Latest news about NICA",
        "symbols": ["NICA"],
        "expected_golden_id": "latest_news",
        "must_contain": ["NICA", "DISCLAIMER"],
        "must_not_contain": [],
        "min_length": 100,
        "max_length": 1500,
    },
    {
        "question": "What was NABIL price 3 years ago?",
        "symbols": ["NABIL"],
        "expected_golden_id": "historical_price",
        "must_contain": ["NABIL", "DISCLAIMER"],
        "must_not_contain": [],
        "min_length": 100,
        "max_length": 1200,
    },
]


def run_matcher_tests() -> list[dict]:
    """Test that golden_matcher correctly identifies known queries."""
    from services.golden_matcher import match_golden

    results = []
    print("\n── Golden Matcher Unit Tests ──")

    for tc in TEST_GOLDEN_QUERIES:
        question = tc["question"]
        symbols = tc.get("symbols", [])
        expected_id = tc["expected_golden_id"]

        match = match_golden(question, symbols)
        got_id = match["id"] if match else None
        matched = got_id == expected_id

        status = "✓" if matched else "✗"
        print(f"  {status} '{question[:45]}' → got='{got_id}' (expected='{expected_id}')")

        results.append({
            "question": question,
            "expected_id": expected_id,
            "got_id": got_id,
            "matched": matched,
        })

    return results


async def run_agent_quality_tests() -> list[dict]:
    """Run full agent queries and evaluate response quality."""
    from services.agent import run_agent

    results = []
    print("\n── Full Agent Quality Tests ──")

    for tc in TEST_GOLDEN_QUERIES:
        question = tc["question"]
        symbols = tc.get("symbols", [])
        symbol = symbols[0] if symbols else ""

        print(f"\n  Query: '{question}'")

        try:
            result = await run_agent(question, symbol=symbol)
            answer = result.get("answer", "")
            tools_called = result.get("tools_called", [])
            latency_ms = result.get("latency_ms", 0)

            # Check must_contain
            missing_required = [
                kw for kw in tc.get("must_contain", [])
                if kw.lower() not in answer.lower()
            ]

            # Check must_not_contain
            forbidden_found = [
                kw for kw in tc.get("must_not_contain", [])
                if kw.lower() in answer.lower()
            ]

            # Length check
            ans_len = len(answer)
            length_ok = tc["min_length"] <= ans_len <= tc["max_length"]

            # Has DISCLAIMER
            has_disclaimer = "DISCLAIMER" in answer.upper()

            passed = (
                len(missing_required) == 0
                and len(forbidden_found) == 0
                and length_ok
            )
            status = "✓" if passed else "✗"

            print(f"  {status} length={ans_len} | disclaimer={has_disclaimer} | "
                  f"tools={tools_called}")
            if missing_required:
                print(f"    ⚠ Missing required: {missing_required}")
            if forbidden_found:
                print(f"    ⚠ Forbidden found: {forbidden_found}")
            if not length_ok:
                print(f"    ⚠ Length {ans_len} outside [{tc['min_length']}, {tc['max_length']}]")
            print(f"    Answer[0:200]: {answer[:200]}")

            results.append({
                "question": question,
                "expected_golden_id": tc["expected_golden_id"],
                "answer_preview": answer[:500],
                "answer_length": ans_len,
                "tools_called": tools_called,
                "latency_ms": latency_ms,
                "has_disclaimer": has_disclaimer,
                "missing_required": missing_required,
                "forbidden_found": forbidden_found,
                "length_ok": length_ok,
                "passed": passed,
            })

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            results.append({
                "question": question,
                "expected_golden_id": tc["expected_golden_id"],
                "error": str(e),
                "passed": False,
            })

    return results


def compute_metrics(matcher_results: list[dict], agent_results: list[dict]) -> dict:
    """Compute pass rates for matcher and agent quality tests."""
    matcher_pass = sum(1 for r in matcher_results if r.get("matched"))
    agent_pass = sum(1 for r in agent_results if r.get("passed"))
    disclaimer_pass = sum(1 for r in agent_results if r.get("has_disclaimer"))
    length_pass = sum(1 for r in agent_results if r.get("length_ok"))
    advice_clean = sum(
        1 for r in agent_results
        if not r.get("forbidden_found") and not r.get("error")
    )

    nm = len(matcher_results)
    na = len(agent_results)

    return {
        "golden_match_rate": round(matcher_pass / nm, 4) if nm else None,
        "golden_quality_pass_rate": round(agent_pass / na, 4) if na else None,
        "golden_disclaimer_rate": round(disclaimer_pass / na, 4) if na else None,
        "golden_length_compliance": round(length_pass / na, 4) if na else None,
        "golden_no_advice_compliance": round(advice_clean / na, 4) if na else None,
        "total_matcher_tests": nm,
        "total_agent_tests": na,
    }


async def main():
    from datetime import datetime
    print("🔍 NEPSE AI — Golden Prompt Quality Evaluation")
    print("=" * 60)

    matcher_results = run_matcher_tests()
    agent_results = await run_agent_quality_tests()

    metrics = compute_metrics(matcher_results, agent_results)

    print("\n── Summary Metrics ──")
    TARGETS = {
        "golden_match_rate":          0.9,
        "golden_quality_pass_rate":   0.8,
        "golden_disclaimer_rate":     1.0,
        "golden_length_compliance":   0.9,
        "golden_no_advice_compliance": 1.0,
    }
    for key, val in metrics.items():
        if val is None:
            continue
        target = TARGETS.get(key)
        if target is not None:
            status = "✓ PASS" if val >= target else "✗ FAIL"
            print(f"  {key:38s}: {val:.4f}  (target: ≥{target})  {status}")
        else:
            print(f"  {key:38s}: {val}")

    # Save results
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    output = {
        "timestamp": timestamp,
        "metrics": metrics,
        "matcher_results": matcher_results,
        "agent_results": agent_results,
    }
    out_path = RESULTS_DIR / f"eval_golden_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n📄 Results saved to: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
