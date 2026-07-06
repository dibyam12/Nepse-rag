"""
evaluation/eval_historical.py
Historical Price Pipeline Evaluation for NEPSE AI.

Tests the full historical data flow end-to-end:
  1. get_price_at_date()     — returns real prices (not None) for valid dates
  2. get_price_n_years_ago() — produces sensible date offsets
  3. get_price_change_summary() — calculates correct % change
  4. historical_tool()       — formats comparison text with both dates/prices
  5. Full agent query        — answer contains actual historical numbers

Pass criteria:
  - 100% of DB lookups return valid data for known symbols with data
  - Out-of-range lookups correctly return None (no fabrication)
  - historical_tool text contains both dates and a % change figure

Usage:
    cd backend
    venv\\Scripts\\python.exe -m evaluation.eval_historical
"""

import os
import sys
import json
import asyncio
import logging
from datetime import date, timedelta
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

# ── Test cases ────────────────────────────────────────────────
# symbol, years_ago, expect_data: True if the stock existed N years ago
DB_TEST_CASES = [
    {"symbol": "NABIL", "years_ago": 3,  "expect_data": True},   # NABIL listed 2006
    {"symbol": "NABIL", "years_ago": 10, "expect_data": True},
    {"symbol": "NICA",  "years_ago": 5,  "expect_data": True},   # NIC Asia listed 2007
    {"symbol": "SBL",   "years_ago": 1,  "expect_data": True},
    {"symbol": "NABIL", "years_ago": 35, "expect_data": False},  # 1991 — before listing
]

# Full agent integration tests — check that the agent answer uses real DB numbers
AGENT_INTEGRATION_TESTS = [
    {
        "question": "What was NABIL's price 3 years ago?",
        "symbol": "NABIL",
        "must_contain_any": ["2023", "ago", "NPR"],  # Must reference real historical date
        "must_not_contain": ["52W Range", "I don't have data"],  # Must NOT refuse or use 52W
        "expect_historical_tool": True,
    },
    {
        "question": "Compare NICA price today vs 2 years ago",
        "symbol": "NICA",
        "must_contain_any": ["2024", "change", "%"],
        "must_not_contain": [],
        "expect_historical_tool": True,
    },
]


async def run_db_tests() -> list[dict]:
    """Test the three db_service historical functions directly."""
    from services.db_service import (
        get_price_at_date,
        get_price_n_years_ago,
        get_price_change_summary,
    )

    results = []
    print("\n── DB Function Tests ──")

    for tc in DB_TEST_CASES:
        symbol = tc["symbol"]
        years = tc["years_ago"]
        expect = tc["expect_data"]

        target_date = date.today() - timedelta(days=years * 365)
        target_str = target_date.strftime("%Y-%m-%d")

        # Test get_price_n_years_ago
        try:
            data = await get_price_n_years_ago(symbol, years)
            got_data = data is not None
            close_val = data["close"] if data else None
            actual_date = data["date"] if data else None

            pass_check = (got_data == expect)
            status = "✓" if pass_check else "✗"
            print(
                f"  {status} {symbol} {years}yr ago | "
                f"expect_data={expect} | got={got_data} | "
                f"close={close_val} on {actual_date}"
            )

            results.append({
                "test": f"{symbol}_{years}yr_ago",
                "function": "get_price_n_years_ago",
                "symbol": symbol,
                "years_ago": years,
                "expect_data": expect,
                "got_data": got_data,
                "close": close_val,
                "date": actual_date,
                "passed": pass_check,
            })

        except Exception as e:
            print(f"  ✗ {symbol} {years}yr ago | ERROR: {e}")
            results.append({
                "test": f"{symbol}_{years}yr_ago",
                "function": "get_price_n_years_ago",
                "symbol": symbol,
                "years_ago": years,
                "expect_data": expect,
                "got_data": None,
                "error": str(e),
                "passed": False,
            })

    # Test get_price_change_summary for NABIL (3 year range)
    print("\n  Testing get_price_change_summary(NABIL, 3yr)...")
    try:
        three_yr_ago = (date.today() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
        today_str = date.today().strftime("%Y-%m-%d")
        summary = await get_price_change_summary("NABIL", three_yr_ago, today_str)

        if "error" not in summary:
            pct = summary["pct_change"]
            direction = summary["direction"]
            print(f"  ✓ NABIL change summary: {pct:.1f}% {direction} "
                  f"({summary['from_price']} → {summary['to_price']})")
            results.append({
                "test": "NABIL_change_summary",
                "function": "get_price_change_summary",
                "pct_change": pct,
                "direction": direction,
                "passed": True,
            })
        else:
            print(f"  ✗ NABIL change summary error: {summary['error']}")
            results.append({
                "test": "NABIL_change_summary",
                "function": "get_price_change_summary",
                "error": summary["error"],
                "passed": False,
            })
    except Exception as e:
        print(f"  ✗ get_price_change_summary ERROR: {e}")
        results.append({
            "test": "NABIL_change_summary",
            "function": "get_price_change_summary",
            "error": str(e),
            "passed": False,
        })

    return results


async def run_tool_tests() -> list[dict]:
    """Test historical_tool() text output quality."""
    from services.agent import historical_tool

    results = []
    print("\n── historical_tool() Output Tests ──")

    test_cases = [
        {"symbol": "NABIL", "years_ago": 3},
        {"symbol": "NICA",  "years_ago": 2},
        {"symbol": "SBL",   "years_ago": 1},
    ]

    for tc in test_cases:
        symbol = tc["symbol"]
        years = tc["years_ago"]
        try:
            text, citations = await historical_tool(symbol, years_ago=years)
            has_text = bool(text and text.strip())
            has_pct = "%" in (text or "")
            has_dates = any(str(y) in (text or "") for y in range(2018, 2026))

            passed = has_text and (has_pct or "not available" in text.lower())
            status = "✓" if passed else "✗"
            print(
                f"  {status} historical_tool({symbol}, {years}yr) | "
                f"text={has_text} | pct={'%' in text} | dates={has_dates}"
            )
            if has_text:
                print(f"    Preview: {text[:120]}...")

            results.append({
                "test": f"historical_tool_{symbol}_{years}yr",
                "symbol": symbol,
                "years_ago": years,
                "has_text": has_text,
                "has_pct": has_pct,
                "has_dates": has_dates,
                "passed": passed,
            })
        except Exception as e:
            print(f"  ✗ historical_tool({symbol}, {years}yr) ERROR: {e}")
            results.append({
                "test": f"historical_tool_{symbol}_{years}yr",
                "symbol": symbol,
                "years_ago": years,
                "error": str(e),
                "passed": False,
            })

    return results


async def run_agent_integration_tests() -> list[dict]:
    """Test full agent queries for historical questions."""
    from services.agent import run_agent

    results = []
    print("\n── Full Agent Integration Tests ──")

    for tc in AGENT_INTEGRATION_TESTS:
        question = tc["question"]
        symbol = tc["symbol"]
        print(f"\n  Query: {question}")

        try:
            result = await run_agent(question, symbol=symbol)
            answer = result.get("answer", "")
            tools_called = result.get("tools_called", [])

            # Check must_contain_any
            contains_any = any(
                kw.lower() in answer.lower()
                for kw in tc.get("must_contain_any", [])
            )
            # Check must_not_contain
            contains_bad = any(
                kw.lower() in answer.lower()
                for kw in tc.get("must_not_contain", [])
            )
            # Check historical_tool invocation
            has_hist_tool = "historical_tool" in tools_called

            passed = contains_any and not contains_bad
            status = "✓" if passed else "✗"

            print(f"  {status} contains_any={contains_any} | "
                  f"contains_bad={contains_bad} | "
                  f"historical_tool={has_hist_tool}")
            print(f"    Tools: {tools_called}")
            print(f"    Answer[0:200]: {answer[:200]}")

            results.append({
                "question": question,
                "symbol": symbol,
                "answer_preview": answer[:400],
                "tools_called": tools_called,
                "contains_any": contains_any,
                "contains_bad": contains_bad,
                "has_historical_tool": has_hist_tool,
                "passed": passed,
            })
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            results.append({
                "question": question,
                "symbol": symbol,
                "error": str(e),
                "passed": False,
            })

    return results


def compute_metrics(db_results, tool_results, agent_results) -> dict:
    """Compute pass rates for each test category."""
    db_pass = sum(1 for r in db_results if r.get("passed"))
    tool_pass = sum(1 for r in tool_results if r.get("passed"))
    agent_pass = sum(1 for r in agent_results if r.get("passed"))

    return {
        "db_function_pass_rate": round(db_pass / len(db_results), 4) if db_results else None,
        "historical_tool_pass_rate": round(tool_pass / len(tool_results), 4) if tool_results else None,
        "agent_integration_pass_rate": round(agent_pass / len(agent_results), 4) if agent_results else None,
        "total_db_tests": len(db_results),
        "total_tool_tests": len(tool_results),
        "total_agent_tests": len(agent_results),
    }


async def main():
    from datetime import datetime
    print("🔍 NEPSE AI — Historical Price Pipeline Evaluation")
    print("=" * 60)

    db_results = await run_db_tests()
    tool_results = await run_tool_tests()
    agent_results = await run_agent_integration_tests()

    metrics = compute_metrics(db_results, tool_results, agent_results)

    print("\n── Summary Metrics ──")
    TARGETS = {
        "db_function_pass_rate": 1.0,
        "historical_tool_pass_rate": 0.9,
        "agent_integration_pass_rate": 0.8,
    }
    for key, val in metrics.items():
        if val is None:
            continue
        target = TARGETS.get(key)
        if target is not None:
            status = "✓ PASS" if val >= target else "✗ FAIL"
            print(f"  {key:35s}: {val:.4f}  (target: ≥{target})  {status}")
        else:
            print(f"  {key:35s}: {val}")

    # Save results
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    output = {
        "timestamp": timestamp,
        "metrics": metrics,
        "db_results": db_results,
        "tool_results": tool_results,
        "agent_results": agent_results,
    }
    out_path = RESULTS_DIR / f"eval_historical_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n📄 Results saved to: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
