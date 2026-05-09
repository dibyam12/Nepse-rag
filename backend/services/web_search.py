# services/web_search.py
"""
Web search fallback chain for NEPSE AI.
Primary: DuckDuckGo with NEPSE site restriction (best for Nepali financial news)
Fallback: NewsAPI (good metadata but limited Nepali coverage)
"""

import asyncio
import logging
from urllib.parse import urlparse

import httpx
from decouple import config

logger = logging.getLogger('nepse_rag')


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url


NEPSE_SITES = [
    "sharesansar.com",
    "merolagani.com",
    "nepsealpha.com",
    "sharehubnepal.com",
    "nepalipaisa.com",
    "eng.bajarkochirfar.com",
    "bajarkochirfar.com",
    "ictframe.com",
    "english.ratopati.com",
    "laganinews.com",
    "onlinekhabar.com",
    "newbusinessage.com",
    "nepsetrading.com",
    "english.khabarhub.com",
]


def _extract_source(r: dict) -> str:
    source = r.get("source", "")
    if source and source.lower() not in ("duckduckgo", ""):
        return source
    url = r.get("url", r.get("href", r.get("link", "")))
    return _extract_domain(url) if url else "web"


async def ddg_search(query: str, count: int = 8) -> list[dict]:
    """
    DuckDuckGo search — primary provider for NEPSE news.
    Tries news search first, falls back to text search.
    Uses two-step strategy: site-restricted first, then general Nepal finance.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        logger.warning("ddg_search: ddgs package not installed")
        return []

    def _run_search() -> list[dict]:
        ddgs_client = DDGS()
        seen_urls: set[str] = set()
        results: list[dict] = []

        # Step 1: site-restricted query — split into smaller batches
        # DDG handles max ~3 site: operators reliably; use two passes
        nepse_sites_a = "site:sharesansar.com OR site:merolagani.com OR site:nepsealpha.com OR site:nepalipaisa.com"
        nepse_sites_b = "site:eng.bajarkochirfar.com OR site:ictframe.com OR site:laganinews.com OR site:nepsetrading.com"

        for site_filter in (nepse_sites_a, nepse_sites_b):
            if len(results) >= count:
                break
            restricted_query = f"{query} ({site_filter})"
            # Try news search
            try:
                for r in ddgs_client.news(restricted_query, max_results=count):
                    url = r.get("url", r.get("href", ""))
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append(r)
            except Exception:
                pass
            # Try text search as fallback
            if not results:
                try:
                    for r in ddgs_client.text(restricted_query, max_results=count):
                        url = r.get("url", r.get("href", ""))
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            results.append(r)
                except Exception:
                    pass

        # Step 2: if still short, general Nepal finance query
        if len(results) < 3:
            general_query = f"{query} Nepal finance bank stock"
            try:
                for r in ddgs_client.news(general_query, max_results=count - len(results)):
                    url = r.get("url", r.get("href", ""))
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append(r)
            except Exception:
                pass

        return results

    try:
        loop = asyncio.get_event_loop()
        raw = await asyncio.wait_for(
            loop.run_in_executor(None, _run_search),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        logger.warning("ddg_search: timed out after 8s for query=%r", query)
        return []
    except Exception as e:
        logger.warning("ddg_search error: %s", e)
        return []

    if not raw:
        logger.debug("ddg_search: 0 results for %r", query)
        return []

    logger.info("ddg_search: %d results for %r", len(raw), query)
    return [
        {
            "title": (r.get("title") or "")[:500],
            "url": r.get("url", r.get("href", r.get("link", ""))),
            "snippet": (r.get("body") or r.get("description") or "")[:500],
            "publishedAt": r.get("date", ""),
            "source": _extract_source(r),
            "source_provider": "duckduckgo",
        }
        for r in raw
        if r.get("url") or r.get("href")
    ]


async def newsapi_search(query: str, count: int = 5) -> list[dict]:
    """
    NewsAPI.org — secondary provider.
    Free tier: 500 requests/month. Good metadata but limited Nepali coverage.
    Filters out articles with None titles (malformed Khabarhub responses).
    """
    api_key = config("NEWSAPI_KEY", default="")
    if not api_key or api_key == "your_newsapi_key_here":
        logger.warning("newsapi_search: key not configured")
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "apiKey": api_key,
                    "pageSize": count,
                    "sortBy": "publishedAt",
                    "language": "en",
                },
            )
        if resp.status_code != 200:
            logger.warning("newsapi_search: HTTP %d", resp.status_code)
            return []

        data = resp.json()
        if data.get("status") != "ok":
            logger.warning("newsapi_search: %s", data.get("message", "error"))
            return []

        articles = data.get("articles", [])
        results = []
        for a in articles:
            title = a.get("title") or ""
            url = a.get("url") or ""
            # Skip articles with no title or placeholder titles
            if not title or title == "[Removed]" or not url:
                continue
            results.append({
                "title": title[:500],
                "url": url,
                "snippet": (a.get("description") or "")[:500],
                "publishedAt": a.get("publishedAt", ""),
                "source": a.get("source", {}).get("name") or _extract_domain(url),
                "source_provider": "newsapi",
            })

        logger.info("newsapi_search: %d valid articles for %r", len(results), query)
        return results

    except Exception as e:
        logger.error("newsapi_search error: %s", e)
        return []


async def web_search(query: str, count: int = 5) -> list[dict]:
    """
    Unified search — DDG first (better for NEPSE), NewsAPI as supplement.
    Returns deduplicated combined results.
    """
    logger.info("web_search: %r", query)

    # Run both concurrently — don't waterfall
    ddg_results, newsapi_results = await asyncio.gather(
        ddg_search(query, count),
        newsapi_search(query, 3),
        return_exceptions=True,
    )

    combined: list[dict] = []
    seen_urls: set[str] = set()

    for batch in (ddg_results, newsapi_results):
        if not isinstance(batch, list):
            continue
        for item in batch:
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                combined.append(item)

    if combined:
        logger.info("web_search: %d combined results", len(combined))
        return combined[:count]

    logger.error("web_search: all providers failed for %r", query)
    return []


async def fetch_article(url: str, max_chars: int = 2000) -> str:
    """Fetches a URL and extracts clean article text."""
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=2.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                },
            )
        if resp.status_code != 200:
            return ""

        from bs4 import BeautifulSoup
        import re

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "noscript", "ads"]):
            tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.find("body")
        if not main:
            return ""

        text = main.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]

    except Exception as e:
        logger.debug("fetch_article error for %s: %s", url, e)
        return ""


# Legacy aliases — keep for backward compatibility
async def google_custom_search(query: str, count: int = 5) -> list[dict]:
    logger.debug("google_custom_search: disabled (403)")
    return []


async def serpapi_search(query: str, count: int = 5) -> list[dict]:
    logger.debug("serpapi_search: disabled (429, no credits)")
    return []
