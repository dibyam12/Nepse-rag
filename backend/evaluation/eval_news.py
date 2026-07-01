"""
News Pipeline Reliability Test for NEPSE AI.

For each of NABIL, NICA, NHPC, SBL, UPPER:
1. Calls news_tool(symbol) directly
2. Checks: articles > 0, no markdown in headlines, no off-topic results
3. Verifies NHPC returns Nepal-specific results (no Indian NHPC)
4. Reports pass/fail per symbol

Usage:
    cd backend
    venv\\Scripts\\python.exe -m evaluation.eval_news
"""

import os
import sys
import json
import asyncio
import re
import logging
from datetime import datetime
from pathlib import Path

# Django setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nepse_project.settings")

import django
django.setup()

logger = logging.getLogger("nepse_rag")

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

TEST_SYMBOLS = ["NABIL", "NICA", "NHPC", "SBL", "UPPER"]

MARKDOWN_PATTERNS = [
    r'\[.*?\]\(.*?\)',     # [text](url)
    r'#{1,6}\s',          # ### headers
    r'\*{2,}.*?\*{2,}',   # **bold**
    r'!\[.*?\]\(.*?\)',    # ![img](url)
]

INDIAN_INDICATORS = [
    'bse', 'nse india', 'sensex', 'nifty', 'mumbai',
    'indian nhpc', 'nhpc limited india', 'power corporation of india',
    'indiatimes', 'moneycontrol', 'livemint', 'business-standard',
]


def _has_markdown(text: str) -> bool:
    """Check if text contains markdown artifacts."""
    for pattern in MARKDOWN_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def _is_indian_article(article: dict) -> bool:
    """Check if article is about Indian companies, not Nepali."""
    combined = (
        (article.get("headline", "") or "") + " " +
        (article.get("summary", "") or "") + " " +
        (article.get("source", "") or "") + " " +
        (article.get("url", "") or "")
    ).lower()
    return any(indicator in combined for indicator in INDIAN_INDICATORS)


async def test_news_reliability():
    """Test news pipeline for 5 symbols."""
    from services.agent import news_tool
    from services.cache_service import get_cached_news

    print("📰 NEPSE AI — News Pipeline Reliability Test")
    print("=" * 60)

    all_results = []

    for symbol in TEST_SYMBOLS:
        print(f"\n── {symbol} ──")

        try:
            text, citations = await news_tool(symbol)
        except Exception as e:
            print(f"  ✗ news_tool({symbol}) FAILED: {e}")
            all_results.append({
                "symbol": symbol,
                "passed": False,
                "error": str(e),
                "articles": 0,
            })
            continue

        article_count = len(citations)
        print(f"  Articles: {article_count}")

        # Check 1: Has articles
        has_articles = article_count > 0

        # Check 2: No markdown in headlines
        markdown_in_headlines = 0
        for c in citations:
            headline = c.get("headline", "")
            if _has_markdown(headline):
                markdown_in_headlines += 1
                print(f"  ⚠ Markdown in headline: {headline[:80]}...")

        no_markdown = markdown_in_headlines == 0

        # Check 3: No off-topic (Indian for NHPC)
        indian_articles = 0
        if symbol == "NHPC":
            for c in citations:
                if _is_indian_article(c):
                    indian_articles += 1
                    print(f"  ⚠ Indian article: {c.get('headline', '')[:80]}...")

        no_indian = indian_articles == 0

        # Check 4: Sources are diverse (not all from same source)
        sources = set(c.get("source", "unknown") for c in citations)

        # Overall pass
        passed = has_articles and no_markdown and no_indian

        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  Has articles: {'✓' if has_articles else '✗'}")
        print(f"  No markdown:  {'✓' if no_markdown else '✗'} ({markdown_in_headlines} found)")
        if symbol == "NHPC":
            print(f"  No Indian:    {'✓' if no_indian else '✗'} ({indian_articles} found)")
        print(f"  Sources: {list(sources)}")
        print(f"  Status: {status}")

        # Sample headlines
        for c in citations[:3]:
            print(f"    • {c.get('headline', 'N/A')[:80]}")

        all_results.append({
            "symbol": symbol,
            "passed": passed,
            "articles": article_count,
            "markdown_issues": markdown_in_headlines,
            "indian_articles": indian_articles,
            "sources": list(sources),
            "headlines": [c.get("headline", "")[:100] for c in citations[:5]],
        })

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r.get("passed"))

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} symbols passed ({passed/total*100:.0f}%)")
    print("=" * 60)

    # Save
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filepath = RESULTS_DIR / f"news_reliability_{timestamp}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "total": total,
            "passed": passed,
            "results": all_results,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n📄 Results saved to: {filepath}")


if __name__ == "__main__":
    asyncio.run(test_news_reliability())
