"""
RAGAS Evaluation Suite for NEPSE AI RAG System.

Runs test queries through the full agent pipeline, collects
(question, answer, contexts, ground_truth) tuples, then evaluates
using RAGAS metrics with Google AI (Gemini) as the LLM judge.

Metrics:
    - faithfulness:       Does the answer only use facts from context?
    - answer_relevancy:   Is the answer relevant to the question?
    - context_precision:  Are retrieved contexts relevant to the question?

Targets:
    - faithfulness     > 0.8
    - answer_relevancy > 0.7
    - context_precision > 0.6

Usage:
    cd backend
    venv\\Scripts\\python.exe -m evaluation.eval_runner
    venv\\Scripts\\python.exe -m evaluation.eval_runner --category anti_hallucination
    venv\\Scripts\\python.exe -m evaluation.eval_runner --output results.json
"""

import os
import sys
import json
import asyncio
import argparse
import logging
from datetime import datetime
from pathlib import Path

# ── Django setup ──────────────────────────────────────────────
# Must happen before importing any Django models or services
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nepse_project.settings")

import django
django.setup()

logger = logging.getLogger("nepse_rag")

# ── Paths ─────────────────────────────────────────────────────
EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = EVAL_DIR / "test_questions.json"
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def load_test_questions(category: str = None) -> list[dict]:
    """Load test questions, optionally filtered by category."""
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        questions = json.load(f)

    if category:
        questions = [q for q in questions if q.get("category") == category]
        print(f"Filtered to {len(questions)} questions in category: {category}")

    return questions


async def run_single_query(question_data: dict) -> dict:
    """
    Run a single query through the full agent pipeline.
    Returns enriched dict with answer, contexts, route, tools, etc.
    """
    from services.agent import run_agent

    question = question_data["question"]
    print(f"  → Running: {question[:60]}...")

    try:
        result = await run_agent(question, symbol="")
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return {
            **question_data,
            "answer": f"ERROR: {e}",
            "contexts": [],
            "route_actual": "error",
            "tools_actual": [],
            "latency_ms": 0,
            "error": str(e),
        }

    # Extract contexts from the agent state (via cached response)
    # The agent doesn't expose raw tool outputs in the response,
    # so we reconstruct from the answer + citations
    contexts = []
    for citation in result.get("citations", []):
        if citation.get("type") == "db":
            contexts.append(f"DB data for {citation.get('symbol', '?')}")
        elif citation.get("type") == "graph":
            contexts.append(citation.get("description", "graph data"))
        elif citation.get("type") == "vector":
            contexts.append(f"From {citation.get('source_file', 'docs')}")
        elif citation.get("type") == "news":
            headline = citation.get("headline", "")
            summary = citation.get("summary", "")
            contexts.append(f"News: {headline}. {summary[:200]}")
        elif citation.get("type") == "web":
            contexts.append(citation.get("description", "web data"))

    # If no citations extracted, use the answer itself as minimal context
    if not contexts:
        contexts = [result.get("answer", "")[:500]]

    return {
        **question_data,
        "answer": result.get("answer", ""),
        "contexts": contexts,
        "route_actual": result.get("route_used", ""),
        "tools_actual": result.get("tools_called", []),
        "latency_ms": result.get("latency_ms", 0),
        "provider": result.get("llm_provider_used", ""),
        "tokens": result.get("tokens_used", 0),
    }


async def run_all_queries(questions: list[dict]) -> list[dict]:
    """Run all test queries sequentially through the agent."""
    results = []
    total = len(questions)

    for i, q in enumerate(questions, 1):
        print(f"\n[{i}/{total}] Category: {q.get('category', '?')}")
        result = await run_single_query(q)
        results.append(result)

    return results


def evaluate_with_ragas(results: list[dict]) -> dict:
    """
    Run RAGAS evaluation on collected results.
    Uses Google AI (Gemini) as the LLM judge.
    """
    try:
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy, context_precision
        from datasets import Dataset
        from langchain_google_genai import ChatGoogleGenerativeAI
        from decouple import config

        api_key = config("GOOGLE_AI_API_KEY", default="")
        if not api_key:
            print("⚠ GOOGLE_AI_API_KEY not set — skipping RAGAS LLM-based metrics")
            return {"error": "No Google AI API key configured"}

        # Build RAGAS dataset
        ragas_data = {
            "question": [r["question"] for r in results],
            "answer": [r["answer"] for r in results],
            "contexts": [r["contexts"] for r in results],
            "ground_truth": [r.get("ground_truth", "") for r in results],
        }
        dataset = Dataset.from_dict(ragas_data)

        # Configure Google AI as LLM judge
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=api_key,
        )

        print("\n🔍 Running RAGAS evaluation (this may take a few minutes)...")
        ragas_result = evaluate(
            dataset=dataset,
            metrics=[faithfulness, answer_relevancy, context_precision],
            llm=llm,
        )

        scores = {
            "faithfulness": round(float(ragas_result["faithfulness"]), 4),
            "answer_relevancy": round(float(ragas_result["answer_relevancy"]), 4),
            "context_precision": round(float(ragas_result["context_precision"]), 4),
        }

        return scores

    except ImportError as e:
        print(f"⚠ RAGAS dependencies not installed: {e}")
        print("  Run: pip install ragas langchain-google-genai datasets")
        return {"error": f"Missing dependency: {e}"}
    except Exception as e:
        print(f"⚠ RAGAS evaluation failed: {e}")
        return {"error": str(e)}


def compute_basic_metrics(results: list[dict]) -> dict:
    """Compute non-RAGAS metrics: route accuracy, tool accuracy, latency."""
    route_correct = 0
    tool_correct = 0
    total_latency = 0
    negative_correct = 0
    negative_total = 0
    hallucination_detected = 0
    hallucination_total = 0

    for r in results:
        # Route accuracy
        if r.get("route_actual") == r.get("expected_route"):
            route_correct += 1

        # Tool accuracy (check if expected tools are subset of actual)
        expected_tools = set(r.get("expected_tools", []))
        actual_tools = set(r.get("tools_actual", []))
        if expected_tools.issubset(actual_tools) or not expected_tools:
            tool_correct += 1

        # Latency
        total_latency += r.get("latency_ms", 0)

        # Negative prompt handling
        if r.get("negative"):
            negative_total += 1
            answer_lower = r.get("answer", "").lower()
            if any(phrase in answer_lower for phrase in [
                "i only discuss nepse",
                "not a nepse",
                "out of scope",
                "i can't help with",
                "not related to nepse",
                "not listed on nepse",
                "nepse-listed stocks",
                "i don't have information",
            ]):
                negative_correct += 1

        # Anti-hallucination check
        if r.get("category") == "anti_hallucination":
            hallucination_total += 1
            answer_lower = r.get("answer", "").lower()
            if any(phrase in answer_lower for phrase in [
                "not available",
                "not in my current data",
                "not in current data",
                "check the company",
                "quarterly report",
                "sharesansar.com",
                "merolagani.com",
            ]):
                hallucination_detected += 1

    n = len(results)
    return {
        "route_accuracy": round(route_correct / n, 4) if n else 0,
        "tool_accuracy": round(tool_correct / n, 4) if n else 0,
        "avg_latency_ms": round(total_latency / n) if n else 0,
        "negative_rejection_rate": round(negative_correct / negative_total, 4) if negative_total else None,
        "anti_hallucination_rate": round(hallucination_detected / hallucination_total, 4) if hallucination_total else None,
        "total_questions": n,
    }


def print_results(results: list[dict], basic_metrics: dict, ragas_scores: dict):
    """Pretty-print evaluation results."""
    print("\n" + "=" * 70)
    print("NEPSE AI RAG — EVALUATION RESULTS")
    print("=" * 70)

    # Per-question summary
    print("\n── Per-Question Results ──")
    for r in results:
        status = "✓" if not r.get("error") else "✗"
        category = r.get("category", "?")
        route_match = "✓" if r.get("route_actual") == r.get("expected_route") else "✗"
        print(f"  {status} [{category:20s}] route={route_match} | {r['question'][:50]}...")
        if r.get("error"):
            print(f"    ERROR: {r['error']}")

    # Basic metrics
    print("\n── Basic Metrics ──")
    for key, value in basic_metrics.items():
        if value is not None:
            print(f"  {key:30s}: {value}")

    # RAGAS scores
    print("\n── RAGAS Scores ──")
    if "error" in ragas_scores:
        print(f"  ⚠ {ragas_scores['error']}")
    else:
        targets = {
            "faithfulness": 0.8,
            "answer_relevancy": 0.7,
            "context_precision": 0.6,
        }
        for metric, score in ragas_scores.items():
            target = targets.get(metric, 0)
            status = "✓ PASS" if score >= target else "✗ FAIL"
            print(f"  {metric:25s}: {score:.4f}  (target: >{target})  {status}")

    print("\n" + "=" * 70)


def save_results(results: list[dict], basic_metrics: dict, ragas_scores: dict, output_path: str = None):
    """Save results to timestamped JSON file."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")

    if output_path:
        filepath = Path(output_path)
    else:
        filepath = RESULTS_DIR / f"ragas_{timestamp}.json"

    output = {
        "timestamp": timestamp,
        "total_questions": len(results),
        "basic_metrics": basic_metrics,
        "ragas_scores": ragas_scores,
        "per_question": [
            {
                "question": r["question"],
                "category": r.get("category"),
                "answer": r.get("answer", "")[:500],
                "route_expected": r.get("expected_route"),
                "route_actual": r.get("route_actual"),
                "tools_expected": r.get("expected_tools"),
                "tools_actual": r.get("tools_actual"),
                "latency_ms": r.get("latency_ms"),
                "negative": r.get("negative", False),
                "error": r.get("error"),
            }
            for r in results
        ],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n📄 Results saved to: {filepath}")


async def main():
    parser = argparse.ArgumentParser(description="NEPSE AI RAGAS Evaluation Suite")
    parser.add_argument("--category", type=str, default=None,
                        help="Filter by category (e.g., anti_hallucination, news_query)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file path (default: evaluation/results/ragas_<timestamp>.json)")
    parser.add_argument("--skip-ragas", action="store_true",
                        help="Skip RAGAS LLM-based metrics (faster, basic metrics only)")
    args = parser.parse_args()

    print("🚀 NEPSE AI RAG — Evaluation Suite")
    print(f"   Questions file: {QUESTIONS_FILE}")

    # Load questions
    questions = load_test_questions(args.category)
    if not questions:
        print("⚠ No test questions found!")
        return

    print(f"   Total questions: {len(questions)}")

    # Run queries
    print("\n── Running Agent Queries ──")
    results = await run_all_queries(questions)

    # Compute basic metrics
    basic_metrics = compute_basic_metrics(results)

    # Run RAGAS evaluation
    ragas_scores = {}
    if not args.skip_ragas:
        # Filter out negative prompts for RAGAS (they don't have meaningful contexts)
        ragas_candidates = [r for r in results if not r.get("negative") and not r.get("error")]
        if ragas_candidates:
            ragas_scores = evaluate_with_ragas(ragas_candidates)
        else:
            ragas_scores = {"error": "No valid candidates for RAGAS evaluation"}
    else:
        ragas_scores = {"skipped": True}

    # Print and save
    print_results(results, basic_metrics, ragas_scores)
    save_results(results, basic_metrics, ragas_scores, args.output)


if __name__ == "__main__":
    asyncio.run(main())
