# services/news_scraper.py
"""
NEPSE-specific news pipeline.

Architecture:
1. Cache check — return immediately on hit (1-hour TTL)
2. Concurrent fetch:
   a. Direct HTML scrape of ShareSansar news page (AJAX endpoint)
   b. Direct HTML scrape of MeroLagani announcements (AJAX endpoint)
   c. DDG site-restricted search (two batches of 4 sites each)
   d. NewsAPI supplemental search
3. Deduplicate by URL
4. Filter Indian stock market sources
5. Normalize output schema
6. Persist to DB (fire-and-forget)
7. Cache and return

NOTE: ShareSansar and MeroLagani company pages load news via JavaScript/AJAX.
Static HTML scraping of those pages returns 0 news results.
Instead we use their dedicated news/announcement JSON endpoints.
"""

import asyncio
import logging
from datetime import date as date_cls

import httpx
from bs4 import BeautifulSoup
from django.utils import timezone

from apps.nepse_data.models import NewsEvent, Stock
from services.web_search import ddg_search, newsapi_search, fetch_article, _extract_domain
from services.cache_service import get_cached_news, cache_news

logger = logging.getLogger("nepse_rag")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}

# Indian financial sites that pollute NEPSE symbol searches (e.g. NHPC = Indian company too)
INDIAN_SOURCES_BLACKLIST = {
    "thehindubusinessline.com",
    "economictimes.indiatimes.com",
    "moneycontrol.com",
    "livemint.com",
    "business-standard.com",
    "financialexpress.com",
    "ndtv.com",
    "zeebiz.com",
    "cnbctv18.com",
    "bseindia.com",
    "nseindia.com",
}


def _current_month_year() -> str:
    return date_cls.today().strftime("%B %Y")


def _is_nepse_article(item: dict) -> bool:
    url = item.get("url", "").lower()
    return not any(domain in url for domain in INDIAN_SOURCES_BLACKLIST)


async def scrape_sharesansar(symbol: str) -> list[dict]:
    """Fetch ShareSansar news via their search endpoint."""
    url = f"https://www.sharesansar.com/newslist?symbol={symbol.upper()}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(6.0, connect=3.0),
            headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        # ShareSansar news list items: <a href="/newsdetail/...">Headline</a>
        for link in soup.select("a[href*='/newsdetail/']")[:8]:
            headline = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.sharesansar.com" + href
            parent = link.parent or link
            date_tag = parent.find(class_=lambda c: c and "date" in c.lower())
            date_text = date_tag.get_text(strip=True) if date_tag else ""
            if headline and len(headline) > 10:
                results.append({
                    "headline": headline,
                    "url": href,
                    "published_date": date_text,
                    "source": "sharesansar.com",
                    "snippet": "",
                })
        return results
    except Exception as e:
        logger.warning("scrape_sharesansar(%s) failed: %s", symbol, e)
        return []


async def scrape_merolagani(symbol: str) -> list[dict]:
    """
    Fetches MeroLagani announcements via their API endpoint.
    MeroLagani loads announcements via AJAX to:
    https://merolagani.com/handlers/AutoCompleteHandler.ashx?type=getCompanyLatestEvents&symbol=NABIL
    """
    api_url = (
        f"https://merolagani.com/handlers/AutoCompleteHandler.ashx"
        f"?type=getCompanyLatestEvents&symbol={symbol.upper()}"
    )
    base_url = "https://merolagani.com"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(6.0, connect=3.0),
            headers={**HEADERS, "Referer": f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(api_url)

        if resp.status_code != 200:
            logger.debug("scrape_merolagani(%s): HTTP %d", symbol, resp.status_code)
            return []

        # Try JSON first
        try:
            data = resp.json()
            results = []
            items = data if isinstance(data, list) else data.get("d", data.get("data", []))
            for item in items[:8]:
                headline = item.get("title") or item.get("subject") or item.get("Title") or ""
                href = item.get("url") or item.get("Url") or item.get("link") or ""
                date_text = item.get("date") or item.get("Date") or item.get("eventDate") or ""
                if href and not href.startswith("http"):
                    href = base_url + "/" + href.lstrip("/")
                if headline and len(headline) > 10:
                    results.append({
                        "headline": headline,
                        "url": href or f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}",
                        "published_date": str(date_text),
                        "source": "merolagani.com",
                        "snippet": item.get("description") or item.get("body") or "",
                    })
            if results:
                logger.debug("scrape_merolagani(%s): %d items from JSON", symbol, len(results))
                return results
        except Exception:
            pass

        # Fallback: parse as HTML
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select("li, tr")[:8]:
            link = item.find("a")
            if not link:
                continue
            headline = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = base_url + "/" + href.lstrip("/")
            if headline and len(headline) > 10:
                results.append({
                    "headline": headline,
                    "url": href or f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}",
                    "published_date": "",
                    "source": "merolagani.com",
                    "snippet": "",
                })

        logger.debug("scrape_merolagani(%s): %d items from HTML fallback", symbol, len(results))
        return results

    except Exception as e:
        logger.warning("scrape_merolagani(%s) failed: %s", symbol, e)
        return []


async def scrape_nepsealpha(symbol: str) -> list[dict]:
    """
    Fetches NepseAlpha news via their company page.
    NepseAlpha renders news server-side — reliable static scraping.
    """
    url = f"https://nepsealpha.com/stocks/{symbol.upper()}/news"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(6.0, connect=3.0),
            headers=HEADERS,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for item in soup.select("div.news-item, article.news, li.news-entry, div.card")[:8]:
            link = item.find("a")
            if not link:
                continue
            headline = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = "https://nepsealpha.com" + href
            if headline and len(headline) > 10:
                results.append({
                    "headline": headline,
                    "url": href,
                    "published_date": "",
                    "source": "nepsealpha.com",
                    "snippet": "",
                })

        logger.debug("scrape_nepsealpha(%s): %d items", symbol, len(results))
        return results

    except Exception as e:
        logger.warning("scrape_nepsealpha(%s) failed: %s", symbol, e)
        return []


def _is_article_url(url: str, symbol: str) -> bool:
    """Returns True if URL looks like an actual article, not a profile/index page."""
    sym = symbol.lower()
    url_lower = url.lower()
    
    # Check explicit skip patterns dynamically
    skip_patterns = (
        f"/company/{sym}",         # ShareSansar / NepaliPaisa
        f"/stocks/{sym}/info",     # NepseAlpha
        "companydetail.aspx",      # MeroLagani
        f"/company/{sym}/",
    )
    if any(skip in url_lower for skip in skip_patterns):
        return False

    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/")
    path_parts = [p for p in path.split("/") if p]
    
    # Skip homepages or empty paths
    if len(path_parts) == 0:
        return False
        
    return True

async def get_news_for_symbol(
    symbol: str,
    stock_name: str = "",
    max_articles: int = 6,
) -> list[dict]:
    """
    Full news pipeline. Returns normalized list of article dicts.
    """
    # Step 1: Cache check
    cached = get_cached_news(symbol)
    if cached:
        logger.debug("get_news_for_symbol(%s): cache hit (%d items)", symbol, len(cached))
        return cached

    # Resolve stock name if not passed
    if not stock_name:
        try:
            from django.apps import apps
            StockModel = apps.get_model("nepse_data", "Stock")
            obj = StockModel.objects.filter(symbol=symbol).first()
            if obj and obj.name and "auto-created" not in obj.name.lower():
                stock_name = obj.name
        except Exception:
            pass

    current_month = _current_month_year()

    # Build two DDG queries — split site lists for reliability
    ddg_query_a = (
        f'"{symbol}" "{stock_name}" after:2026-01-01 ' if stock_name else f'"{symbol}" after:2026-01-01 '
    ) + f"(site:sharesansar.com OR site:merolagani.com OR site:nepsealpha.com OR site:nepalipaisa.com)"

    ddg_query_b = (
        f'"{stock_name}" after:2026-01-01 ' if stock_name else f'"{symbol}" after:2026-01-01 '
    ) + f"(site:eng.bajarkochirfar.com OR site:ictframe.com OR site:laganinews.com OR site:nepsetrading.com)"

    newsapi_query = f'"{stock_name or symbol}" NEPSE {current_month}'

    logger.info(
        "get_news_for_symbol(%s): stock_name=%r, month=%s",
        symbol, stock_name, current_month,
    )

    # Step 2: Concurrent fetch — all sources in parallel
    (
        scrape_ss,
        scrape_ml,
        scrape_na,
        ddg_a,
        ddg_b,
        newsapi_res,
    ) = await asyncio.gather(
        scrape_sharesansar(symbol),
        scrape_merolagani(symbol),
        scrape_nepsealpha(symbol),
        ddg_search(ddg_query_a, count=5),
        ddg_search(ddg_query_b, count=5),
        newsapi_search(newsapi_query, count=3),
        return_exceptions=True,
    )

    # Step 3: Merge all results
    all_items: list[dict] = []
    for batch in (scrape_ss, scrape_ml, scrape_na, ddg_a, ddg_b, newsapi_res):
        if isinstance(batch, list):
            all_items.extend(batch)

    logger.info(
        "get_news_for_symbol(%s): raw counts — ss=%s ml=%s na=%s ddg_a=%s ddg_b=%s newsapi=%s total=%d",
        symbol,
        len(scrape_ss) if isinstance(scrape_ss, list) else f"ERR:{scrape_ss}",
        len(scrape_ml) if isinstance(scrape_ml, list) else f"ERR:{scrape_ml}",
        len(scrape_na) if isinstance(scrape_na, list) else f"ERR:{scrape_na}",
        len(ddg_a) if isinstance(ddg_a, list) else f"ERR:{ddg_a}",
        len(ddg_b) if isinstance(ddg_b, list) else f"ERR:{ddg_b}",
        len(newsapi_res) if isinstance(newsapi_res, list) else f"ERR:{newsapi_res}",
        len(all_items),
    )

    # Step 4: Deduplicate by URL
    seen_urls: set[str] = set()
    unique_items: list[dict] = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)

    # Step 5: Filter Indian sources and non-article profile pages
    unique_items = [item for item in unique_items if _is_nepse_article(item)]
    
    # Apply profile page filter
    filtered_items = []
    for item in unique_items:
        url = item.get("url", "")
        # Check path depth and explicit patterns heuristic
        if not _is_article_url(url, symbol):
            continue
        filtered_items.append(item)
    unique_items = filtered_items

    # Step 6: Normalize schema — handle both scraper and search result field names
    for item in unique_items:
        if not item.get("summary"):
            item["summary"] = (
                item.get("snippet")
                or item.get("description")
                or item.get("headline")
                or item.get("title")
                or ""
            )
        # Normalize title field
        if not item.get("title"):
            item["title"] = item.get("headline", "")
        if not item.get("headline"):
            item["headline"] = item.get("title", "")

    # Step 7: Persist to DB (fire-and-forget)
    try:
        from asgiref.sync import sync_to_async

        @sync_to_async
        def _save():
            stock_obj = Stock.objects.filter(symbol=symbol).first()
            for item in unique_items[:max_articles]:
                try:
                    NewsEvent.objects.update_or_create(
                        url=item["url"],
                        defaults={
                            "symbol": stock_obj,
                            "headline": (item.get("headline") or item.get("title", ""))[:500],
                            "source": (item.get("source") or "web")[:200],
                            "summary": item.get("summary", "")[:2000],
                            "published_date": _parse_date(
                                item.get("published_date") or item.get("publishedAt")
                            ),
                        },
                    )
                except Exception:
                    pass

        asyncio.create_task(_save())
    except Exception as e:
        logger.warning("get_news_for_symbol: DB save error: %s", e)

    # Step 8: Build output
    output = [
        {
            "headline": (item.get("headline") or item.get("title", ""))[:200],
            "url": item.get("url", ""),
            "summary": item.get("summary", "")[:500],
            "published_date": (
                item.get("published_date") or item.get("publishedAt", "")
            ),
            "source": item.get("source") or item.get("source_provider", "web"),
            "symbol": symbol,
        }
        for item in unique_items[:max_articles]
    ]

    # Step 9: Cache for 1 hour
    cache_news(symbol, output)

    logger.info("get_news_for_symbol(%s): returning %d articles", symbol, len(output))
    return output


def _parse_date(date_str):
    if not date_str:
        return None
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%B %d, %Y", "%d %b %Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(date_str)[:19], fmt).date()
        except ValueError:
            continue
    return None
