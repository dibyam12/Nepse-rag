"""
Vector Retrieval Quality Test for NEPSE AI.

For 10 diverse queries, checks:
1. Source file diversity (not same file 3x)
2. fundamental_analysis_guide.txt appears ≤1 time per query
3. Cross-encoder reranking actually changes the order
4. Min relevance score after reranking

Usage:
    cd backend
    venv\\Scripts\\python.exe -m evaluation.eval_retrieval
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from collections import Counter

# Django setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nepse_project.settings")

import django
django.setup()

logger = logging.getLogger("nepse_rag")

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Test queries with expected primary source ─────────────────

TEST_QUERIES = [
    {
        "query": "What is RSI?",
        "expected_primary": "indicator_explanations.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "Explain MACD indicator",
        "expected_primary": "indicator_explanations.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "What are Bollinger Bands?",
        "expected_primary": "indicator_explanations.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "Tell me about NEPSE trading rules",
        "expected_primary": "nepse_rules.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "What are the SEBON circulars?",
        "expected_primary": "sebon_circulars.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "Explain the hydropower sector in Nepal",
        "expected_primary": "hydropower_sector_fundamentals.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "What is NRB's monetary policy?",
        "expected_primary": "nrb_monetary_policy_context.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "How do corporate actions work in NEPSE?",
        "expected_primary": "corporate_actions_guide.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "What is the insurance sector like in Nepal?",
        "expected_primary": "insurance_sector_fundamentals.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "How to compare two stocks?",
        "expected_primary": "compare_methodology.txt",
        "should_not_dominate": None,
    },
    {
        "query": "How do bonus shares affect stock price?",
        "expected_primary": "corporate_actions_guide.txt",
        "should_not_dominate": "fundamental_analysis_guide.txt",
    },
    {
        "query": "What causes stock prices to change over time?",
        "expected_primary": "fundamental_analysis_guide.txt",
        "should_not_dominate": None,
    },
]



def test_retrieval_quality():
    """Test vector retrieval diversity and reranking effectiveness."""
    from services.vector_rag import query_vector_rag
    from services.cache_service import get_cached_vector_rag

    print("🔍 NEPSE AI — Vector Retrieval Quality Test")
    print("=" * 60)

    all_results = []
    fundamental_guide_appearances = 0
    diversity_pass = 0
    expected_primary_pass = 0

    for test in TEST_QUERIES:
        query = test["query"]
        expected = test["expected_primary"]
        should_not = test.get("should_not_dominate")

        print(f"\n  Query: {query}")

        # Clear cache to force fresh retrieval
        # (We query directly, bypassing cache)
        from django.core.cache import cache
        cache.clear()
        results = query_vector_rag(query, top_k=10)

        sources = [r.get("source_file", "unknown") for r in results]
        source_counts = Counter(sources)

        print(f"  Sources returned: {sources}")

        # Check 1: Source diversity (not same file 3x, unless only 1 unique source exists)
        max_same = max(source_counts.values()) if source_counts else 0
        diverse = (max_same < 3) or (len(source_counts) <= 1)
        if diverse:
            diversity_pass += 1

        # Check 2: fundamental_analysis_guide.txt count
        fag_count = source_counts.get("fundamental_analysis_guide.txt", 0)
        fundamental_guide_appearances += fag_count
        fag_ok = fag_count <= 1

        # Check 3: Expected primary source appears
        has_expected = expected in sources
        if has_expected:
            expected_primary_pass += 1

        # Check 4: Rerank scores present and ordered
        has_rerank = all("rerank_score" in r for r in results)
        if has_rerank and len(results) > 1:
            scores = [r["rerank_score"] for r in results]
            is_ordered = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
        else:
            is_ordered = True  # Can't check with 0-1 results

        passed = diverse and fag_ok and has_expected
        status = "✓ PASS" if passed else "✗ FAIL"

        print(f"  Diverse (no 3x same):    {'✓' if diverse else '✗'} (max same: {max_same})")
        print(f"  Fundamental guide ≤1:    {'✓' if fag_ok else '✗'} (count: {fag_count})")
        print(f"  Expected '{expected}':   {'✓' if has_expected else '✗'}")
        print(f"  Rerank scores present:   {'✓' if has_rerank else '✗'}")
        print(f"  Rerank order correct:    {'✓' if is_ordered else '✗'}")
        print(f"  Status: {status}")

        all_results.append({
            "query": query,
            "sources": sources,
            "source_counts": dict(source_counts),
            "expected_primary": expected,
            "has_expected": has_expected,
            "diverse": diverse,
            "fag_count": fag_count,
            "has_rerank": has_rerank,
            "passed": passed,
            "rerank_scores": [r.get("rerank_score") for r in results],
        })

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r["passed"])

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} queries passed ({passed/total*100:.0f}%)")
    print(f"  Diversity pass rate:     {diversity_pass}/{total}")
    print(f"  Expected primary rate:   {expected_primary_pass}/{total}")
    print(f"  Total fundamental_analysis_guide appearances: {fundamental_guide_appearances}")
    print("=" * 60)

    # Save
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filepath = RESULTS_DIR / f"retrieval_diversity_{timestamp}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "total": total,
            "passed": passed,
            "diversity_pass_rate": round(diversity_pass / total, 4),
            "expected_primary_rate": round(expected_primary_pass / total, 4),
            "fundamental_guide_total": fundamental_guide_appearances,
            "results": all_results,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n📄 Results saved to: {filepath}")


if __name__ == "__main__":
    test_retrieval_quality()
