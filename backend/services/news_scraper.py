# services/news_scraper.py
"""
NEPSE-specific news scrapers.
Scrapes sharesansar.com and merolagani.com directly (no API key needed).
Falls back to web_search for additional coverage.
"""

import asyncio
import logging
from datetime import date as date_cls

import httpx
from bs4 import BeautifulSoup
from django.utils import timezone

from apps.nepse_data.models import NewsEvent, Stock
from services.web_search import web_search, fetch_article
from services.cache_service import get_cached_news, cache_news

logger = logging.getLogger('nepse_rag')

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _current_month_year() -> str:
    """Returns e.g. 'May 2026' — keeps all web search queries temporally fresh."""
    return date_cls.today().strftime("%B %Y")


async def scrape_sharesansar(symbol: str) -> list[dict]:
    """
    Scrapes https://www.sharesansar.com/company/{symbol}
    Returns list of {headline, url, published_date, source: 'sharesansar'}.
    Returns [] on any error.
    """
    url = f"https://www.sharesansar.com/company/{symbol}"
    try:
        async with httpx.AsyncClient(
            timeout=5.0, headers=HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for item in soup.select(
            ".company-news-item, .news-list li, .featured-news-list li"
        )[:10]:
            link = item.find("a")
            if not link:
                continue
            headline = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.sharesansar.com" + href
            date_tag = item.find(class_=lambda c: c and "date" in c.lower())
            published_date = date_tag.get_text(strip=True) if date_tag else ""
            if headline and href:
                results.append({
                    "headline": headline,
                    "url": href,
                    "published_date": published_date,
                    "source": "sharesansar",
                })

        logger.debug("scrape_sharesansar(%s): %d items", symbol, len(results))
        return results

    except Exception as e:
        logger.warning("scrape_sharesansar(%s) failed: %s", symbol, e)
        return []


async def scrape_merolagani(symbol: str) -> list[dict]:
    """
    Scrapes https://www.merolagani.com/CompanyDetail.aspx?symbol={symbol}
    Returns list of {headline, url, published_date, source: 'merolagani'}.
    Returns [] on any error.
    """
    url = f"https://www.merolagani.com/CompanyDetail.aspx?symbol={symbol}"
    try:
        async with httpx.AsyncClient(
            timeout=5.0, headers=HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for item in soup.select(
            ".company-news li, #divNewsContainer li, .news-section li"
        )[:10]:
            link = item.find("a")
            if not link:
                continue
            headline = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.merolagani.com/" + href.lstrip("/")
            date_tag = item.find(class_=lambda c: c and "date" in c.lower())
            published_date = date_tag.get_text(strip=True) if date_tag else ""
            if headline and href:
                results.append({
                    "headline": headline,
                    "url": href,
                    "published_date": published_date,
                    "source": "merolagani",
                })

        logger.debug("scrape_merolagani(%s): %d items", symbol, len(results))
        return results

    except Exception as e:
        logger.warning("scrape_merolagani(%s) failed: %s", symbol, e)
        return []


async def get_news_for_symbol(
    symbol: str, max_articles: int = 5
) -> list[dict]:
    """
    Full news pipeline for a symbol.

    Step 1: Check Django cache — return immediately on hit.
    Step 2: Run scrape_sharesansar + scrape_merolagani + web_search concurrently.
            FIX: web_search query now includes current month/year (e.g. "May 2026")
                 instead of a bare year, so results are always fresh.
    Step 3: Deduplicate by URL.
    Step 4: Fetch full text for top 2 articles via fetch_article().
    Step 5: Persist to NewsEvent model.
    Step 6: Cache result for 1 hour.
    Step 7: Return normalised list of dicts.
    """
    # Step 1: Cache check
    cached = get_cached_news(symbol)
    if cached:
        logger.debug("get_news_for_symbol(%s): cache hit", symbol)
        return cached

    # Resolve human-readable stock name for richer search queries
    stock_name = ""
    try:
        from django.apps import apps
        StockModel = apps.get_model('nepse_data', 'Stock')
        stock_obj = StockModel.objects.filter(symbol=symbol).first()
        if stock_obj:
            stock_name = stock_obj.name
    except Exception:
        pass

    # FIX 2: Use current month + year so web_search returns fresh articles,
    # not results from months ago that happen to match "2026".
    current_month = _current_month_year()   # e.g. "May 2026"
    search_query = f"{symbol} {stock_name} Nepal {current_month}".strip()

    logger.debug(
        "get_news_for_symbol(%s): search_query=%r", symbol, search_query
    )

    # Step 2: Concurrent fetch
    scrape_ss, scrape_ml, search_results = await asyncio.gather(
        scrape_sharesansar(symbol),
        scrape_merolagani(symbol),
        web_search(search_query, count=5),
        return_exceptions=True,
    )

    all_items: list[dict] = []
    for r in [scrape_ss, scrape_ml, search_results]:
        if isinstance(r, list):
            all_items.extend(r)

    # Step 3: Deduplicate by URL
    seen_urls: set[str] = set()
    unique_items: list[dict] = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)

    # Step 4: Fetch full text for top 2 articles
    top2 = unique_items[:2]
    full_texts = await asyncio.gather(
        *[fetch_article(item["url"]) for item in top2],
        return_exceptions=True,
    )
    for i, text in enumerate(full_texts):
        if isinstance(text, str) and text:
            top2[i]["summary"] = text[:500]

    # Ensure all items have a summary field
    for item in unique_items:
        if "summary" not in item:
            item["summary"] = item.get("snippet", "")

    # Step 5: Persist to NewsEvent model
    try:
        from asgiref.sync import sync_to_async

        @sync_to_async
        def save_to_db():
            stock_obj = Stock.objects.filter(symbol=symbol).first()
            for item in unique_items[:max_articles]:
                NewsEvent.objects.update_or_create(
                    url=item["url"],
                    defaults={
                        "symbol": stock_obj,
                        "headline": (
                            item.get("headline") or item.get("title", "")
                        )[:500],
                        "source": (
                            item.get("source") or item.get("source_provider", "web")
                        ),
                        "summary": item.get("summary", "")[:2000],
                        "published_date": _parse_date(
                            item.get("published_date")
                        ),
                    },
                )

        await save_to_db()
    except Exception as e:
        logger.warning(
            "get_news_for_symbol: DB save failed for %s: %s", symbol, e
        )

    # Normalise output shape
    output = [
        {
            "headline": (
                item.get("headline") or item.get("title", "")
            )[:200],
            "url":            item.get("url", ""),
            "summary":        item.get("summary", "")[:500],
            "published_date": item.get("published_date", ""),
            "source":         item.get("source") or item.get("source_provider", "web"),
            "symbol":         symbol,
        }
        for item in unique_items[:max_articles]
    ]

    # Step 6: Cache (1 hour)
    cache_news(symbol, output)

    logger.info(
        "get_news_for_symbol(%s): returned %d articles",
        symbol, len(output),
        extra={"event": "news_fetch", "symbol": symbol, "count": len(output)},
    )
    return output


def _parse_date(date_str: str):
    """Tries to parse a date string to a Python date. Returns None on failure."""
    if not date_str:
        return None
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(date_str[:20], fmt).date()
        except ValueError:
            continue
    return None