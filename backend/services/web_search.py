# services/web_search.py
"""
Web search fallback chain for NEPSE AI.
Primary:  DuckDuckGo (best for Nepali financial news, no key needed)
Fallback: NewsAPI (good metadata, 500 req/month free)

Key fixes vs previous version:
- Uses timelimit='m' in DDG for past-month results (replaces broken after: filter)
- Separates site: queries — DDG handles max 1-2 site: operators reliably
- Uses both .news() and .text() with proper exception handling per ddgs API
- Adds GNews API support (100 req/day free — sign up at gnews.io)
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


def _extract_source(r: dict) -> str:
    source = r.get("source", "")
    if source and source.lower() not in ("duckduckgo", ""):
        return source
    url = r.get("url", r.get("href", r.get("link", "")))
    return _extract_domain(url) if url else "web"


# ─────────────────────────────────────────────
# PRIMARY: DuckDuckGo
# ─────────────────────────────────────────────

NEPSE_SITES_PRIMARY = [
    "sharesansar.com",
    "merolagani.com",
    "nepsealpha.com",
    "nepalipaisa.com",
]

NEPSE_SITES_SECONDARY = [
    "ictframe.com",
    "laganinews.com",
    "onlinekhabar.com",
    "nepsetrading.com",
    "sharehubnepal.com",
]


def _run_ddg_query(query: str, count: int, timelimit: str = "m") -> list[dict]:
    """
    Synchronous DDG search — runs inside executor.
    Tries .news() first (structured), falls back to .text().
    timelimit: 'd'=day, 'w'=week, 'm'=month, 'y'=year
    """
    try:
        from ddgs import DDGS
    except ImportError:
        logger.warning("ddg: ddgs package not installed — pip install ddgs")
        return []

    results = []
    seen_urls: set[str] = set()

    try:
        with DDGS() as ddgs:
            # Try news search first — returns structured recent articles
            try:
                for r in ddgs.news(query, max_results=count, timelimit=timelimit):
                    url = r.get("url", r.get("href", ""))
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append(r)
            except Exception as e:
                logger.debug("ddg.news() failed: %s — trying text()", e)

            # If news returned nothing, try text search
            if not results:
                try:
                    for r in ddgs.text(query, max_results=count, timelimit=timelimit):
                        url = r.get("url", r.get("href", ""))
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            results.append(r)
                except Exception as e:
                    logger.debug("ddg.text() failed: %s", e)

    except Exception as e:
        logger.warning("DDG DDGS() init failed: %s", e)

    return results


INDEX_TITLE_PATTERNS = [
    "Nepal Stock Exchange (NEPSE) Listed Companies",
    "Nepal Stock Exchange (NEPSE) News, Live Trading",
    "Nepal Share Market Company Announcements",
    "NEPSE Listed Companies",
    "ShareSansar Forum",
]


def _is_index_result(r: dict) -> bool:
    title = (r.get("title") or "").strip()
    return any(pat.lower() in title.lower() for pat in INDEX_TITLE_PATTERNS)


def _normalize_ddg(raw: list[dict]) -> list[dict]:
    return [
        {
            "title": (r.get("title") or "")[:500],
            "url": r.get("url", r.get("href", r.get("link", ""))),
            "snippet": (r.get("body") or r.get("description") or r.get("excerpt") or "")[:500],
            "publishedAt": r.get("date", "") or r.get("published", ""),
            "source": _extract_source(r),
            "source_provider": "duckduckgo",
            "headline": (r.get("title") or "")[:500],
        }
        for r in raw
        if (r.get("url") or r.get("href")) and not _is_index_result(r)
    ]


async def ddg_search(query: str, count: int = 6) -> list[dict]:
    """
    DuckDuckGo search with timelimit='m' (past month).
    Runs two queries: site-restricted (primary) + general Nepal finance.
    Both run concurrently for speed.
    """
    # Pick the most relevant site based on query content
    site = "sharesansar.com"  # default
    query_lower = query.lower()
    if "merolagani" in query_lower:
        site = "merolagani.com"
    elif "nepsealpha" in query_lower or "alpha" in query_lower:
        site = "nepsealpha.com"

    site_query = f"{query} site:{site}"
    general_query = f"{query} Nepal stock market"

    loop = asyncio.get_event_loop()

    try:
        site_raw, general_raw = await asyncio.gather(
            asyncio.wait_for(
                loop.run_in_executor(None, _run_ddg_query, site_query, count, "m"),
                timeout=7.0,
            ),
            asyncio.wait_for(
                loop.run_in_executor(None, _run_ddg_query, general_query, count, "m"),
                timeout=7.0,
            ),
            return_exceptions=True,
        )
    except Exception as e:
        logger.warning("ddg_search gather failed: %s", e)
        return []

    merged = []
    seen: set[str] = set()

    for batch in (site_raw, general_raw):
        if not isinstance(batch, list):
            continue
        for item in batch:
            url = item.get("url", item.get("href", ""))
            if url and url not in seen:
                seen.add(url)
                merged.append(item)

    if not merged:
        # Last resort: plain query no site restriction, expand to year
        try:
            fallback_raw = await asyncio.wait_for(
                loop.run_in_executor(None, _run_ddg_query, query, count, "y"),
                timeout=7.0,
            )
            merged = fallback_raw if isinstance(fallback_raw, list) else []
        except Exception:
            pass

    normalized = _normalize_ddg(merged)
    logger.info("ddg_search(%r): %d results", query[:60], len(normalized))
    return normalized[:count]


async def ddg_search_multi_site(symbol: str, stock_name: str = "", count: int = 8) -> list[dict]:
    """
    Runs separate DDG queries per Nepali site for a given stock symbol.
    More reliable than OR chains — DDG handles one site: per query best.
    Called by news_scraper.py for targeted symbol-level news fetching.
    """
    company_part = stock_name.split()[0] if stock_name else symbol

    # Build per-site queries — one site: per query for reliability
    site_queries = [
        (f"{symbol} {company_part} site:sharesansar.com", "sharesansar.com"),
        (f"{symbol} {company_part} site:merolagani.com", "merolagani.com"),
        (f"{symbol} {company_part} site:nepsealpha.com", "nepsealpha.com"),
        (f"{symbol} Nepal stock site:ictframe.com", "ictframe.com"),
        (f"{company_part} Nepal site:onlinekhabar.com", "onlinekhabar.com"),
    ]

    loop = asyncio.get_event_loop()

    tasks = [
        asyncio.wait_for(
            loop.run_in_executor(None, _run_ddg_query, q, 4, "m"),
            timeout=6.0,
        )
        for q, _ in site_queries
    ]

    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items = []
    seen: set[str] = set()

    for (_, site_name), batch in zip(site_queries, batch_results):
        if not isinstance(batch, list):
            continue
        for item in batch:
            url = item.get("url", item.get("href", ""))
            if url and url not in seen:
                seen.add(url)
                item["source"] = site_name
                all_items.append(item)

    normalized = _normalize_ddg(all_items)
    logger.info(
        "ddg_search_multi_site(%s): %d results across %d sites",
        symbol, len(normalized), len(site_queries),
    )
    return normalized[:count]


# ─────────────────────────────────────────────
# SECONDARY: NewsAPI
# ─────────────────────────────────────────────

async def newsapi_search(query: str, count: int = 5) -> list[dict]:
    """
    NewsAPI.org — secondary provider.
    Free tier: 500 requests/month. Good metadata, limited Nepali coverage.
    """
    api_key = config("NEWSAPI_KEY", default="")
    if not api_key or api_key in ("your_newsapi_key_here", ""):
        logger.debug("newsapi_search: key not configured, skipping")
        return []

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
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

        if resp.status_code == 429:
            logger.warning("newsapi_search: rate limited (429) — monthly quota likely exhausted")
            return []

        if resp.status_code != 200:
            logger.warning("newsapi_search: HTTP %d", resp.status_code)
            return []

        data = resp.json()
        if data.get("status") != "ok":
            logger.warning("newsapi_search: %s", data.get("message", "unknown error"))
            return []

        results = []
        for a in data.get("articles", []):
            title = a.get("title") or ""
            url = a.get("url") or ""
            if not title or title == "[Removed]" or not url:
                continue
            results.append({
                "title": title[:500],
                "headline": title[:500],
                "url": url,
                "snippet": (a.get("description") or "")[:500],
                "publishedAt": a.get("publishedAt", ""),
                "source": a.get("source", {}).get("name") or _extract_domain(url),
                "source_provider": "newsapi",
            })

        logger.info("newsapi_search: %d valid articles for %r", len(results), query[:60])
        return results

    except Exception as e:
        logger.error("newsapi_search error: %s", e)
        return []


# ─────────────────────────────────────────────
# TERTIARY: GNews API (free, 100 req/day)
# ─────────────────────────────────────────────

async def gnews_search(symbol: str, stock_name: str = "", count: int = 5) -> list[dict]:
    """
    GNews API — free tier: 100 requests/day, recent news only.
    Sign up at https://gnews.io (no credit card needed).
    Add GNEWS_API_KEY to your .env to enable.
    """
    api_key = config("GNEWS_API_KEY", default="")
    if not api_key or api_key in ("your_gnews_key_here", ""):
        logger.debug("gnews_search: GNEWS_API_KEY not configured, skipping")
        return []

    name_part = stock_name.split()[0] if stock_name else symbol
    query = f"{symbol} {name_part} Nepal stock"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://gnews.io/api/v4/search",
                params={
                    "q": query,
                    "lang": "en",
                    "max": count,
                    "apikey": api_key,
                    "sortby": "publishedAt",
                },
            )

        if resp.status_code == 403:
            logger.warning("gnews_search: 403 — quota exhausted or invalid key")
            return []

        if resp.status_code != 200:
            logger.warning("gnews_search: HTTP %d", resp.status_code)
            return []

        data = resp.json()
        results = []
        for art in data.get("articles", []):
            title = art.get("title", "")
            url = art.get("url", "")
            if not title or not url:
                continue
            results.append({
                "title": title[:500],
                "headline": title[:500],
                "url": url,
                "snippet": (art.get("description") or "")[:500],
                "publishedAt": (art.get("publishedAt") or "")[:10],
                "published_date": (art.get("publishedAt") or "")[:10],
                "source": art.get("source", {}).get("name") or _extract_domain(url),
                "source_provider": "gnews",
            })

        logger.info("gnews_search(%s): %d results", symbol, len(results))
        return results

    except Exception as e:
        logger.warning("gnews_search(%s) error: %s", symbol, e)
        return []


# ─────────────────────────────────────────────
# ARTICLE FETCHER
# ─────────────────────────────────────────────

# Site-specific CSS selectors for Nepali financial sites
SITE_SELECTORS = {
    "sharesansar.com": [".news-detail-content", ".news-content", ".post-body"],
    "merolagani.com":  [".news-content", ".announcement-detail", ".content-area"],
    "nepsealpha.com":  [".article-content", ".news-body", ".post-content"],
    "nepalstock.com":  [".announcement-detail", ".content", "main"],
    "ictframe.com":    [".entry-content", ".post-content", "article"],
    "onlinekhabar.com": [".ok18-single-post-content", ".post-content"],
}

GENERIC_SELECTORS = [
    ".news-content", ".post-content", ".article-body", ".entry-content",
    "#news-detail", ".news-detail-content", ".news-detail",
    ".announcement-detail", "article", "main",
]

BOILERPLATE_PATTERNS = [
    r"(?i)click here to download.*?\.",
    r"(?i)copyright\s+©.*?\.",
    r"(?i)all rights reserved.*?\.",
    r"(?i)subscribe to our newsletter.*?\.",
    r"(?i)read also.*?\.",
    r"(?i)advertisement\b.*?\.",
    r"(?i)follow us on.*?\.",
]


async def fetch_article(url: str, max_chars: int = 1500) -> dict:
    """
    Fetches a URL via Tinyfish API and extracts clean markdown text + title.
    Returns {"text": str, "title": str}.
    Falls back to direct httpx fetch if Tinyfish fails.
    """
    empty_res = {"text": "", "title": ""}
    if not url:
        return empty_res

    import re

    tinyfish_key = config("TINYFISH_API_KEY", default="")
    if tinyfish_key:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.fetch.tinyfish.ai",
                    json={"urls": [url], "format": "markdown"},
                    headers={
                        "X-API-Key": tinyfish_key,
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                if results:
                    r = results[0]
                    text = re.sub(r"\s+", " ", str(r.get("text", ""))).strip()
                    title = str(r.get("title", "")).strip()
                    # Strip common site suffixes from title
                    for suffix in (" - ShareSansar", " | ShareSansar",
                                   " - MeroLagani", " | MeroLagani",
                                   " - NepseAlpha", " || ShareSansar ||"):
                        if title.lower().endswith(suffix.lower()):
                            title = title[:-len(suffix)].strip()
                    if text and len(text) > 50:
                        return {"text": text[:max_chars], "title": title}
        except Exception as e:
            logger.debug("fetch_article tinyfish(%s) error: %s", url, e)

    domain = _extract_domain(url)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=2.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        ) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            return empty_res

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract page title
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
            # Strip common suffixes
            suffixes = (
                " - ShareSansar", " | ShareSansar",
                " - MeroLagani", " | MeroLagani",
                " - Nepalipaisa", " | Nepalipaisa",
                " - NepseAlpha", " | NepseAlpha",
            )
            for suffix in suffixes:
                if title.lower().endswith(suffix.lower()):
                    title = title[:-len(suffix)]
            title = title.strip()

        # Remove noise tags
        for tag in soup(["script", "style", "nav", "footer", "noscript",
                         "iframe", "aside", "form", "button"]):
            tag.decompose()

        # Try site-specific selectors first, then generic
        main = None
        selectors_to_try = SITE_SELECTORS.get(domain, []) + GENERIC_SELECTORS

        for selector in selectors_to_try:
            main = soup.select_one(selector)
            if main and len(main.get_text(strip=True)) > 100:
                break

        if not main:
            main = soup.find("body")

        if not main:
            return empty_res

        text = main.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()

        # Strip boilerplate
        for pattern in BOILERPLATE_PATTERNS:
            text = re.sub(pattern, "", text)

        text = re.sub(r"\s+", " ", text).strip()
        return {"text": text[:max_chars], "title": title}

    except Exception as e:
        logger.debug("fetch_article(%s) error: %s", url, e)
        return empty_res


# ─────────────────────────────────────────────
# UNIFIED SEARCH
# ─────────────────────────────────────────────

async def web_search(query: str, count: int = 5) -> list[dict]:
    """
    Unified search — DDG + NewsAPI concurrently.
    Returns deduplicated combined results.
    """
    logger.info("web_search: %r", query[:80])

    ddg_results, newsapi_results = await asyncio.gather(
        ddg_search(query, count),
        newsapi_search(query, 3),
        return_exceptions=True,
    )

    combined: list[dict] = []
    seen: set[str] = set()

    for batch in (ddg_results, newsapi_results):
        if not isinstance(batch, list):
            continue
        for item in batch:
            url = item.get("url", "")
            if url and url not in seen:
                seen.add(url)
                combined.append(item)

    logger.info("web_search: %d combined results", len(combined))
    return combined[:count]


# Legacy aliases
async def google_custom_search(query: str, count: int = 5) -> list[dict]:
    logger.debug("google_custom_search: disabled (403)")
    return []


async def serpapi_search(query: str, count: int = 5) -> list[dict]:
    logger.debug("serpapi_search: disabled (429, no credits)")
    return []
