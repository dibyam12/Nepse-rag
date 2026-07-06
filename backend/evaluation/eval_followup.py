"""
evaluation/eval_followup.py
Follow-Up & Conversation Context Evaluation for NEPSE AI.

Runs sequential query pairs and verifies:
  1. Symbol resolution — follow-up questions resolve to the correct stock
  2. Signal omission  — redundant price cards are suppressed for follow-ups
  3. No-advice compliance — 'should I buy?' never uses forbidden phrases
  4. Non-repetition   — consecutive responses vary in structure

Pass criteria:
  - Symbol correctly resolved in ≥ 90% of follow-ups
  - No forbidden advice phrases in any response
  - Responses vary in structure (no verbatim copy of opening sentence)

Usage:
    cd backend
    venv\\Scripts\\python.exe -m evaluation.eval_followup
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


# ── Conversation flow definitions ─────────────────────────────

CONVERSATION_FLOWS = [
    {
        "name": "Single stock follow-up",
        "description": "Ask about NABIL, then ask a follow-up. Symbol must stay NABIL.",
        "turns": [
            {
                "question": "Show me NABIL indicators",
                "symbol": "",
                "expected_symbol": "NABIL",
                "check_no_advice": False,
                "check_omit_signals": False,
            },
            {
                "question": "Should I buy it?",
                "symbol": "NABIL",   # sent as context symbol (lastSymbol)
                "expected_symbol": "NABIL",
                "check_no_advice": True,
                "check_omit_signals": True,  # follow-up should omit price cards
            },
            {
                "question": "What about its news?",
                "symbol": "NABIL",
                "expected_symbol": "NABIL",
                "check_no_advice": False,
                "check_omit_signals": False,
            },
        ],
    },
    {
        "name": "Compare then follow-up",
        "description": "Compare two stocks, then ask a follow-up about the comparison.",
        "turns": [
            {
                "question": "Compare NICA and NCCB",
                "symbol": "",
                "expected_symbol": "NICA",
                "check_no_advice": False,
                "check_omit_signals": False,
            },
            {
                "question": "Which one has better momentum?",
                "symbol": "NICA",
                "expected_symbol": "NICA",
                "check_no_advice": True,
                "check_omit_signals": True,
            },
        ],
    },
    {
        "name": "Switch symbol mid-conversation",
        "description": "Ask about NABIL, then explicitly switch to NICA.",
        "turns": [
            {
                "question": "NABIL price",
                "symbol": "",
                "expected_symbol": "NABIL",
                "check_no_advice": False,
                "check_omit_signals": False,
            },
            {
                "question": "Now show me NICA",
                "symbol": "NABIL",  # old context symbol
                "expected_symbol": "NICA",  # should switch to new explicit symbol
                "check_no_advice": False,
                "check_omit_signals": False,
            },
        ],
    },
]


FORBIDDEN_ADVICE_PHRASES = [
    "i would recommend",
    "i would caution against buying",
    "you should buy",
    "you should sell",
    "consider purchasing",
    "it might be a good time to buy",
    "i recommend",
    "my recommendation",
]


async def run_conversation_flow(flow: dict) -> dict:
    """Run a single conversation flow and record results."""
    from services.agent import run_agent

    flow_name = flow["name"]
    print(f"\n── Flow: {flow_name} ──")
    print(f"   {flow['description']}")

    turns_results = []
    prev_answer = ""

    for i, turn in enumerate(flow["turns"]):
        question = turn["question"]
        context_symbol = turn.get("symbol", "")
        expected_symbol = turn.get("expected_symbol", "")
        check_no_advice = turn.get("check_no_advice", False)
        check_omit_signals = turn.get("check_omit_signals", False)

        print(f"\n  Turn {i+1}: '{question}' (context_symbol='{context_symbol}')")

        try:
            result = await run_agent(question, symbol=context_symbol)
            answer = result.get("answer", "")
            signals = result.get("signals") or {}
            tools_called = result.get("tools_called", [])

            # Symbol resolution: check that expected_symbol is mentioned in answer
            symbol_resolved = expected_symbol.upper() in answer.upper() if expected_symbol else True

            # No-advice: check for forbidden phrases
            no_advice_ok = True
            violated_phrase = None
            if check_no_advice:
                for phrase in FORBIDDEN_ADVICE_PHRASES:
                    if phrase in answer.lower():
                        no_advice_ok = False
                        violated_phrase = phrase
                        break

            # Non-repetition: compare opening sentence with previous turn's answer
            non_repeat_ok = True
            if prev_answer and answer:
                prev_open = prev_answer[:80].lower().strip()
                curr_open = answer[:80].lower().strip()
                if prev_open and curr_open and prev_open == curr_open:
                    non_repeat_ok = False

            # Signal omission: for follow-up turns, signals should be empty/None
            # We can only check this via API, but agent returns signals dict
            # Heuristic: if check_omit_signals, we verify signals is empty-ish
            signals_omitted = True
            if check_omit_signals:
                # The agent run_agent() doesn't apply omit_signals logic
                # (that's done in the view layer). We note this limitation.
                signals_omitted = None  # Not testable via run_agent() directly

            turn_passed = symbol_resolved and no_advice_ok
            status = "✓" if turn_passed else "✗"

            print(f"  {status} symbol_resolved={symbol_resolved} | "
                  f"no_advice={no_advice_ok} | non_repeat={non_repeat_ok}")
            print(f"    Tools: {tools_called}")
            if not no_advice_ok:
                print(f"    ⚠ Forbidden phrase found: '{violated_phrase}'")
            print(f"    Answer[0:150]: {answer[:150]}")

            turns_results.append({
                "turn": i + 1,
                "question": question,
                "context_symbol": context_symbol,
                "expected_symbol": expected_symbol,
                "symbol_resolved": symbol_resolved,
                "no_advice_ok": no_advice_ok,
                "violated_phrase": violated_phrase,
                "non_repeat_ok": non_repeat_ok,
                "signals_omitted": signals_omitted,
                "tools_called": tools_called,
                "answer_preview": answer[:300],
                "passed": turn_passed,
            })

            prev_answer = answer

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            turns_results.append({
                "turn": i + 1,
                "question": question,
                "error": str(e),
                "passed": False,
            })

    flow_passed = all(t.get("passed") for t in turns_results)
    return {
        "flow_name": flow_name,
        "turns": turns_results,
        "flow_passed": flow_passed,
    }


def compute_metrics(flow_results: list[dict]) -> dict:
    """Compute aggregate metrics across all conversation flows."""
    total_turns = 0
    symbol_correct = 0
    no_advice_violations = 0
    no_advice_total = 0
    non_repeat_ok_count = 0
    non_repeat_total = 0
    flows_passed = 0

    for flow in flow_results:
        if flow.get("flow_passed"):
            flows_passed += 1

        for turn in flow.get("turns", []):
            total_turns += 1

            if turn.get("symbol_resolved") is not None:
                if turn["symbol_resolved"]:
                    symbol_correct += 1

            if turn.get("no_advice_ok") is not None:
                # Track advice check turns
                if turn.get("check_no_advice") or "should" in turn.get("question", "").lower():
                    no_advice_total += 1
                    if not turn.get("no_advice_ok", True):
                        no_advice_violations += 1

            if turn.get("non_repeat_ok") is not None and turn["turn"] > 1:
                non_repeat_total += 1
                if turn["non_repeat_ok"]:
                    non_repeat_ok_count += 1

    return {
        "symbol_resolution_accuracy": round(symbol_correct / total_turns, 4) if total_turns else None,
        "no_advice_compliance": round(1 - no_advice_violations / no_advice_total, 4) if no_advice_total else None,
        "non_repetition_score": round(non_repeat_ok_count / non_repeat_total, 4) if non_repeat_total else None,
        "flows_passed": flows_passed,
        "total_flows": len(flow_results),
        "total_turns": total_turns,
    }


async def main():
    from datetime import datetime
    print("🔍 NEPSE AI — Follow-Up & Conversation Context Evaluation")
    print("=" * 60)

    all_flow_results = []

    for flow in CONVERSATION_FLOWS:
        result = await run_conversation_flow(flow)
        all_flow_results.append(result)

    metrics = compute_metrics(all_flow_results)

    print("\n── Summary Metrics ──")
    TARGETS = {
        "symbol_resolution_accuracy": 0.9,
        "no_advice_compliance":       1.0,
        "non_repetition_score":       0.8,
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
        "flows": all_flow_results,
    }
    out_path = RESULTS_DIR / f"eval_followup_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n📄 Results saved to: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
