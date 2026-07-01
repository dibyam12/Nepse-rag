# services/news_scraper.py
"""
NEPSE-specific news pipeline.

Source priority (all run concurrently):
  1. ShareSansar  — AJAX/HTML endpoint (multiple selector fallbacks)
  2. MeroLagani   — AJAX JSON endpoint
  3. NepseAlpha   — JSON API then HTML fallback with expanded selectors
  4. NepalStock   — official NEPSE site (stable HTML)
  5. RSS feeds    — ShareSansar + MeroLagani (most stable format)
  6. DDG multi-site — one query per Nepali site (most reliable DDG strategy)
  7. NewsAPI      — supplemental, good metadata
  8. GNews        — if GNEWS_API_KEY configured (100 req/day free)

Key changes vs previous version:
- RSS feeds added via feedparser (install: pip install feedparser)
- DDG now uses ddg_search_multi_site() — one site: per query, no broken OR chains
- No after:2026-01-01 filter (DDG ignores it silently), uses timelimit='m' instead
- NepseAlpha tries JSON API first, then HTML with expanded selectors
- NepalStock official announcements scraper added
- _enrich_articles only runs for articles with NO summary (avoids wasted fetches)
- Individual per-source timeouts so one slow source never blocks others
- DB save moved to fire-and-forget helper (no Django top-level imports)
"""

import asyncio
import logging
from datetime import date as date_cls, datetime

import httpx
from bs4 import BeautifulSoup

from services.web_search import (
    ddg_search,
    ddg_search_multi_site,
    newsapi_search,
    gnews_search,
    fetch_article,
    _extract_domain,
)
from services.cache_service import get_cached_news, cache_news

logger = logging.getLogger("nepse_rag")

# --- Relevance Filter for news_scraper (Change 3A) ---
import re
from datetime import datetime, timedelta

FINANCIAL_KEYWORDS = [
    'dividend', 'ipo', 'agm', 'egm', 'bonus', 'right share',
    'profit', 'loss', 'eps', 'quarter', 'annual report', 'merger',
    'acquisition', 'capital', 'interest rate', 'nrb', 'sebon',
    'listing', 'delisting', 'price', 'volume', 'trading',
    'bank', 'finance', 'insurance', 'hydropower', 'microfinance',
    'nepse', 'share', 'stock', 'ltp', 'market'
]

TITLE_BLOCKLIST = [
    'performing in nepal', 'concert', 'movie', 'cricket', 'football',
    'live video', 'weather', 'election', 'politics', 'tourism',
    'recipe', 'health tip', 'festival'
]

# Symbols that clash with Indian/global companies — require Nepal context
AMBIGUOUS_SYMBOLS = {'NHPC', 'NTC', 'SBI', 'API', 'NFS'}
NEPAL_MARKERS = ['nepal', 'nepse', 'nepali', 'kathmandu', 'nrb', 'sebon', 'pokhara', 'biratnagar']
NEPAL_DOMAINS = ['sharesansar', 'merolagani', 'nepsealpha', 'nepalstock', 'nepalipaisa', 'sharehubnepal', '.com.np']

def _strip_markdown(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'#{1,6}\s*', '', text)        # headers
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)  # bold/italic
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # links
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _is_relevant_news(article: dict, symbol: str, stock_name: str = "") -> bool:
    """
    Relevance filter: symbol OR company name first word must appear
    somewhere in title+excerpt. Generic financial keywords alone are NOT enough.
    """
    title = (article.get('title', '') or article.get('headline', '') or '').lower()
    excerpt = (article.get('excerpt', '') or article.get('summary', '') or article.get('body', '') or article.get('snippet', '') or '').lower()
    text = title + ' ' + excerpt

    # Block obviously irrelevant titles
    if any(block in title for block in TITLE_BLOCKLIST):
        return False

    # Symbol OR company name first word must appear in text
    symbol_lower = symbol.lower()
    first_word = stock_name.split()[0].lower() if stock_name else ""

    symbol_match = symbol_lower in text
    name_match = first_word and len(first_word) > 2 and first_word in text

    if not symbol_match and not name_match:
        return False

    # Stricter check for non-primary sources (not sharesansar/merolagani/nepsealpha)
    # The symbol or company name first word must appear in the title specifically.
    nepal_financial_sources = {'sharesansar.com', 'merolagani.com', 'nepsealpha.com'}
    source = article.get('source', '').lower()
    is_primary = any(p in source for p in nepal_financial_sources)
    if not is_primary:
        url = article.get('url', '')
        if url:
            try:
                domain = _extract_domain(url).lower()
                if any(p in domain for p in nepal_financial_sources):
                    is_primary = True
            except Exception:
                pass

    if not is_primary:
        title_symbol_match = symbol_lower in title
        title_name_match = first_word and len(first_word) > 2 and first_word in title
        if not title_symbol_match and not title_name_match:
            return False

    # Filter articles older than 6 months if date is available
    pub_date = article.get('published_at') or article.get('date') or article.get('published_date') or article.get('publishedAt')
    if pub_date:
        try:
            if isinstance(pub_date, str):
                parsed_dt = _parse_date(pub_date)
                if parsed_dt:
                    parsed = datetime.combine(parsed_dt, datetime.min.time())
                else:
                    parsed = datetime.fromisoformat(pub_date.replace('Z', '+00:00')[:19])
            else:
                import datetime as dt_mod
                if isinstance(pub_date, dt_mod.date) and not isinstance(pub_date, dt_mod.datetime):
                    parsed = datetime.combine(pub_date, datetime.min.time())
                else:
                    parsed = pub_date
            
            if datetime.now() - parsed > timedelta(days=180):
                return False
        except Exception:
            pass

    # Extra disambiguation for symbols that clash with Indian/global companies
    # e.g. NHPC (Nepal) vs NHPC (India), NTC (Nepal) vs NTC (India)
    if symbol.upper() in AMBIGUOUS_SYMBOLS:
        combined_text = (title + ' ' + excerpt + ' ' + article.get('source', '')).lower()
        url = (article.get('url', '') or '').lower()
        has_nepal = any(m in combined_text or m in url for m in NEPAL_MARKERS)
        has_nepal_domain = any(d in url for d in NEPAL_DOMAINS)
        if not has_nepal and not has_nepal_domain:
            return False

    return True

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}

# Indian financial sites that pollute NEPSE symbol searches
# (e.g. NHPC, NIFTY, etc. match Indian companies too)
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
    "equitypandit.com",
    "tickertape.in",
    "screener.in",
    "valueresearchonline.com",
}

RSS_FEEDS = {
    "sharesansar-rss": "https://www.sharesansar.com/rss/news",
    "merolagani-rss": "https://merolagani.com/rss.aspx",
}


def _current_month_year() -> str:
    return date_cls.today().strftime("%B %Y")


def _is_nepse_article(item: dict) -> bool:
    url = (item.get("url") or "").lower()
    source = (item.get("source") or "").lower()
    combined = url + " " + source
    return not any(domain in combined for domain in INDIAN_SOURCES_BLACKLIST)


def _is_article_url(url: str, symbol: str) -> bool:
    """Returns True if URL looks like an article, not a profile/index page."""
    if not url:
        return False
    url_lower = url.lower()

    # Block index / forum / tag / category pages
    index_patterns = (
        "/category/", "/tag/", "/page/", "/author/",
        "/rss", "/feed", "/forum", "/topic.php",
        "companydetail.aspx", "/company/", "/sector/",
        "/index", "index.php", "index.html",
        "merolagani.com/companydetail", "merolagani.com/newslist",
        "sharesansar.com/category", "sharesansar.com/company",
        "/live-trading", "latestmarket.aspx", "/latestmarket",
        "todaysshareprice.aspx", "/todays-share-price", "floorsheet",
        "/market-summary", "/market-overview", "/stocks/", "/symbol/",
        "/company-detail/", "/search", "/trending-stocks", "/trending",
    )
    if any(p in url_lower for p in index_patterns):
        return False

    sym = symbol.lower()
    skip_patterns = (
        f"/company/{sym}",
        f"/stocks/{sym}/info",
        f"/symbol/{sym}",
        f"/company-detail/{sym}",
    )
    if any(p in url_lower for p in skip_patterns):
        return False

    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/")
    return len([p for p in path.split("/") if p]) > 0


async def _get_company_name(symbol: str) -> str:
    """Fetch company name from local SQLite for better search quality."""
    def _fetch():
        try:
            from django.apps import apps
            StockModel = apps.get_model("nepse_data", "Stock")
            obj = StockModel.objects.filter(symbol=symbol).first()
            if obj and obj.name and "auto-created" not in obj.name.lower():
                return " ".join(obj.name.split()[:2])
        except Exception as e:
            logger.warning("_get_company_name(%s) failed: %s", symbol, e)
        return ""
    return await asyncio.to_thread(_fetch)


# ─────────────────────────────────────────────
# SOURCE 1: ShareSansar
# ─────────────────────────────────────────────

async def scrape_sharesansar(symbol: str) -> list[dict]:
    """
    ShareSansar AJAX endpoint — returns company-specific news.
    First GETs the company detail page to extract token and companyid,
    then POSTs to /company-news to fetch real news items.
    """
    url = f"https://www.sharesansar.com/company/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=4.0),
            headers=HEADERS,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("scrape_sharesansar(%s) GET page failed: %d", symbol, resp.status_code)
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Extract CSRF token
            token_tag = soup.find('meta', attrs={'name': '_token'})
            token = token_tag.get('content') if token_tag else None
            
            # Extract internal company ID
            company_id_tag = soup.find(id='companyid')
            company_id = company_id_tag.get_text(strip=True) if company_id_tag else None

            if not token or not company_id:
                logger.warning("scrape_sharesansar(%s) token or companyid not found", symbol)
                return []

            # POST to /company-news
            post_url = "https://www.sharesansar.com/company-news"
            post_headers = {
                **HEADERS,
                "X-CSRF-Token": token,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": url,
            }
            post_data = {
                "company": company_id,
                "draw": "1",
                "start": "0",
                "length": "12",
                "search[value]": "",
                "search[regex]": "false",
            }
            
            post_resp = await client.post(post_url, headers=post_headers, data=post_data)
            if post_resp.status_code != 200:
                logger.warning("scrape_sharesansar(%s) POST news failed: %d", symbol, post_resp.status_code)
                return []

            news_data = post_resp.json()
            data_list = news_data.get('data', [])
            results = []

            for item in data_list:
                title_html = item.get("title", "")
                if not title_html:
                    continue
                # Parse title and href from HTML link tag inside title
                title_soup = BeautifulSoup(title_html, "html.parser")
                a_tag = title_soup.find("a")
                if not a_tag:
                    continue
                headline = a_tag.get_text(strip=True)
                href = a_tag.get("href", "")
                
                date_text = item.get("published_date") or ""

                if headline and len(headline) > 10:
                    results.append({
                        "headline": headline,
                        "url": href,
                        "published_date": date_text,
                        "source": "sharesansar.com",
                        "snippet": "",
                    })

            logger.debug("scrape_sharesansar(%s): found %d news items", symbol, len(results))
            return results

    except Exception as e:
        logger.warning("scrape_sharesansar(%s) failed: %s", symbol, e)
    return []


# ─────────────────────────────────────────────
# SOURCE 2: MeroLagani
# ─────────────────────────────────────────────

async def scrape_merolagani(symbol: str) -> list[dict]:
    """MeroLagani AJAX JSON endpoint for company announcements."""
    api_url = (
        f"https://merolagani.com/handlers/AutoCompleteHandler.ashx"
        f"?type=getCompanyLatestEvents&symbol={symbol.upper()}"
    )
    base_url = "https://merolagani.com"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=4.0),
            headers={
                **HEADERS,
                "Referer": f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}",
            },
            follow_redirects=True,
        ) as client:
            resp = await client.get(api_url)

        if resp.status_code != 200:
            return []

        # Check if response is HTML (redirected to 404.aspx page served with status 200)
        if "html" in resp.headers.get("content-type", "").lower() or resp.text.strip().startswith("<!DOCTYPE"):
            logger.debug("scrape_merolagani(%s): handler returned HTML instead of JSON (likely 404 page)", symbol)
            return []

        # Try JSON first
        try:
            data = resp.json()
            items = (
                data if isinstance(data, list)
                else data.get("d", data.get("data", data.get("items", [])))
            )
            results = []
            for item in items[:8]:
                headline = (
                    item.get("title") or item.get("subject") or
                    item.get("Title") or item.get("Subject") or ""
                )
                href = (
                    item.get("url") or item.get("Url") or
                    item.get("link") or item.get("Link") or ""
                )
                date_text = (
                    item.get("date") or item.get("Date") or
                    item.get("eventDate") or item.get("EventDate") or ""
                )
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
                return results
        except Exception:
            pass

        # HTML fallback
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select("li, tr, .announcement-item")[:8]:
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
        return results

    except Exception as e:
        logger.warning("scrape_merolagani(%s) failed: %s", symbol, e)
        return []


# ─────────────────────────────────────────────
# SOURCE 3: NepseAlpha
# ─────────────────────────────────────────────

async def scrape_nepsealpha(symbol: str) -> list[dict]:
    """
    NepseAlpha — tries JSON API first, then HTML with expanded selectors.
    """
    sym = symbol.upper()

    # Endpoint 1: JSON API
    json_url = f"https://nepsealpha.com/nepse/1/company/{sym}/news"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=4.0),
            headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(json_url)

        if resp.status_code == 200:
            try:
                data = resp.json()
                items = data.get("data", data.get("news", data if isinstance(data, list) else []))
                results = []
                for item in items[:8]:
                    headline = item.get("title") or item.get("heading") or item.get("name") or ""
                    href = item.get("url") or item.get("link") or item.get("slug") or ""
                    if href and not href.startswith("http"):
                        href = "https://nepsealpha.com" + ("/" if not href.startswith("/") else "") + href
                    date_text = str(item.get("date") or item.get("created_at") or "")[:10]
                    if headline and len(headline) > 10:
                        results.append({
                            "headline": headline,
                            "url": href,
                            "published_date": date_text,
                            "source": "nepsealpha.com",
                            "snippet": item.get("content") or item.get("summary") or "",
                        })
                if results:
                    logger.debug("scrape_nepsealpha(%s): %d items from JSON API", sym, len(results))
                    return results
            except Exception:
                pass
    except Exception:
        pass

    # Endpoint 2: HTML page with expanded selectors
    html_url = f"https://nepsealpha.com/stocks/{sym}/news"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=4.0),
            headers=HEADERS,
            follow_redirects=True,
        ) as client:
            resp = await client.get(html_url)

        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        selector_groups = [
            "div.news-wrapper a",
            "div.company-news a",
            "ul.news-list li a",
            "div.news-list a",
            ".stock-news a",
            "table.news-table td a",
            ".card-body a",
            ".list-group-item a",
            "div.news-item a",
            "article.news a",
            "li.news-entry a",
            "div.card a",
            "a[href*='/news/']",
            "a[href*='/article/']",
        ]

        links = []
        used_sel = ""
        for sel in selector_groups:
            found = soup.select(sel)
            if found:
                links = found
                used_sel = sel
                break

        results = []
        for link in links[:8]:
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

        logger.debug(
            "scrape_nepsealpha(%s): %d items from HTML (selector=%r)",
            sym, len(results), used_sel,
        )
        return results

    except Exception as e:
        logger.warning("scrape_nepsealpha(%s) HTML failed: %s", sym, e)
        return []


# ─────────────────────────────────────────────
# SOURCE 4: NepalStock.com (Official NEPSE)
# ─────────────────────────────────────────────

async def scrape_nepalstock(symbol: str) -> list[dict]:
    """
    Official NEPSE website — company announcements.
    Stable government site, no anti-scraping, no JS rendering needed.
    """
    url = f"https://nepalstock.com/company/detail/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=4.0),
            headers=HEADERS,
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        # NEPSE uses a data table for announcements
        for sel in ("table.table tbody tr", ".announcement-list li", "div.announcement a"):
            rows = soup.select(sel)
            if not rows:
                continue
            for row in rows[:6]:
                cols = row.select("td")
                link = row.select_one("a")
                if cols:
                    title = cols[0].get_text(strip=True)
                    date = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                elif link:
                    title = link.get_text(strip=True)
                    date = ""
                else:
                    continue
                href = ""
                if link:
                    href = link.get("href", "")
                    if href and not href.startswith("http"):
                        href = "https://nepalstock.com" + href
                if title and len(title) > 10:
                    results.append({
                        "headline": title,
                        "url": href or url,
                        "published_date": date,
                        "source": "nepalstock.com",
                        "snippet": "",
                    })
            if results:
                break

        logger.debug("scrape_nepalstock(%s): %d items", symbol, len(results))
        return results

    except Exception as e:
        logger.warning("scrape_nepalstock(%s) failed: %s", symbol, e)
        return []


# ─────────────────────────────────────────────
# SOURCE 5: RSS Feeds
# ─────────────────────────────────────────────

async def fetch_rss_for_symbol(symbol: str, source_name: str, feed_url: str) -> list[dict]:
    """
    Fetch RSS feed and filter entries mentioning the symbol or company name.
    RSS is the most stable format — never breaks from HTML redesigns.
    Requires: pip install feedparser
    """
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed — run: pip install feedparser")
        return []

    company_name = (await _get_company_name(symbol)).lower()
    sym_lower = symbol.lower()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                feed_url,
                headers={"User-Agent": HEADERS["User-Agent"]},
            )

        feed = feedparser.parse(resp.text)
        results = []

        for entry in feed.entries[:50]:
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            title_lower = title.lower()
            summary_lower = summary.lower()

            # Match symbol or first word of company name
            first_word = company_name.split()[0] if company_name else ""
            match = (
                sym_lower in title_lower or
                sym_lower in summary_lower or
                (first_word and first_word in title_lower)
            )

            if match:
                pub_date = ""
                if hasattr(entry, "published"):
                    pub_date = (entry.published or "")[:10]

                results.append({
                    "headline": title,
                    "url": entry.get("link", ""),
                    "published_date": pub_date,
                    "summary": summary[:400],
                    "snippet": summary[:400],
                    "source": source_name,
                })

        logger.debug("fetch_rss_for_symbol(%s, %s): %d matches", symbol, source_name, len(results))
        return results[:6]

    except Exception as e:
        logger.warning("fetch_rss_for_symbol(%s, %s) failed: %s", symbol, source_name, e)
        return []


# ─────────────────────────────────────────────
# ENRICHMENT
# ─────────────────────────────────────────────

async def _enrich_articles(articles: list[dict], max_enrich: int = 4) -> list[dict]:
    """
    Fetch full article body and actual page title for top articles.
    Individual 4s timeout per article — runs concurrently, never blocks the pipeline.
    """
    tasks = []
    indices = []

    for i, article in enumerate(articles[:max_enrich]):
        if article.get("url"):
            # Check if we already have a long body (e.g. from RSS/scrapers)
            if not article.get("body") or len(article.get("body")) < 100:
                tasks.append(
                    asyncio.wait_for(
                        fetch_article(article["url"], max_chars=1000),
                        timeout=4.0,
                    )
                )
                indices.append(i)

    if not tasks:
        return articles

    bodies = await asyncio.gather(*tasks, return_exceptions=True)

    enriched = 0
    for idx, res in zip(indices, bodies):
        if isinstance(res, dict) and res.get("text") and len(res["text"]) > 80:
            articles[idx]["body"] = res["text"]
            articles[idx]["summary"] = res["text"][:500]
            articles[idx]["snippet"] = res["text"][:500]
            if res.get("title"):
                articles[idx]["headline"] = res["title"]
                articles[idx]["title"] = res["title"]
            enriched += 1

    if enriched:
        logger.debug("_enrich_articles: enriched %d/%d articles", enriched, len(tasks))

    return articles


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

async def get_news_for_symbol(
    symbol: str,
    stock_name: str = "",
    max_articles: int = 6,
) -> list[dict]:
    """
    Full news pipeline — all sources concurrent, individual timeouts.
    Returns normalized list of article dicts ready for LLM context.
    """
    # Cache check
    cached = get_cached_news(symbol)
    if cached:
        logger.debug("get_news_for_symbol(%s): cache hit (%d items)", symbol, len(cached))
        return cached

    if not stock_name:
        stock_name = await _get_company_name(symbol)

    current_month = _current_month_year()
    newsapi_query = f"{stock_name or symbol} NEPSE {current_month}"

    logger.info(
        "get_news_for_symbol(%s): stock_name=%r month=%s",
        symbol, stock_name, current_month,
    )

    # ── Concurrent fetch from ALL sources ──────────────────────
    # Each wrapped in wait_for so a slow source never blocks others
    source_coros = {
        "sharesansar":     asyncio.wait_for(scrape_sharesansar(symbol), timeout=12.0),
        "merolagani":      asyncio.wait_for(scrape_merolagani(symbol), timeout=12.0),
        "nepsealpha":      asyncio.wait_for(scrape_nepsealpha(symbol), timeout=12.0),
        "nepalstock":      asyncio.wait_for(scrape_nepalstock(symbol), timeout=12.0),
        "rss-sharesansar": asyncio.wait_for(
            fetch_rss_for_symbol(symbol, "sharesansar-rss", RSS_FEEDS["sharesansar-rss"]),
            timeout=10.0,
        ),
        "rss-merolagani":  asyncio.wait_for(
            fetch_rss_for_symbol(symbol, "merolagani-rss", RSS_FEEDS["merolagani-rss"]),
            timeout=10.0,
        ),
        "ddg-multisite":   asyncio.wait_for(
            ddg_search_multi_site(symbol, stock_name, count=8),
            timeout=15.0,
        ),
        "newsapi":         asyncio.wait_for(newsapi_search(newsapi_query, count=4), timeout=12.0),
        "gnews":           asyncio.wait_for(gnews_search(symbol, stock_name, count=5), timeout=12.0),
    }

    source_names = list(source_coros.keys())
    results = await asyncio.gather(*source_coros.values(), return_exceptions=True)

    # Merge and log per-source counts
    all_items: list[dict] = []
    for name, batch in zip(source_names, results):
        if isinstance(batch, list):
            logger.debug("get_news_for_symbol(%s): %s → %d items", symbol, name, len(batch))
            all_items.extend(batch)
        else:
            err_type = type(batch).__name__
            logger.warning("get_news_for_symbol(%s): %s → %s: %s", symbol, name, err_type, batch)

    logger.info("get_news_for_symbol(%s): raw total=%d", symbol, len(all_items))

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)

    # Filter Indian sources
    unique = [i for i in unique if _is_nepse_article(i)]

    # Filter profile/index pages
    unique = [i for i in unique if _is_article_url(i.get("url", ""), symbol)]

    # Filter by relevance (Change 3B)
    unique = [a for a in unique if _is_relevant_news(a, symbol, stock_name)]

    # Sort by recency — items with dates first
    def _sort_key(item):
        d = item.get("published_date") or item.get("publishedAt") or ""
        return str(d)

    unique.sort(key=_sort_key, reverse=True)

    logger.info("get_news_for_symbol(%s): after dedup+filter=%d", symbol, len(unique))

    # Enrich top articles that have no summary (strict outer timeout)
    if unique:
        try:
            unique = await asyncio.wait_for(
                _enrich_articles(unique, max_enrich=4),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.warning("get_news_for_symbol(%s): enrichment timed out", symbol)
        except Exception as e:
            logger.warning("get_news_for_symbol(%s): enrichment error: %s", symbol, e)

    # Normalize schema
    for item in unique:
        if not item.get("summary"):
            item["summary"] = (
                item.get("snippet") or item.get("description") or
                item.get("headline") or ""
            )
        if not item.get("headline"):
            item["headline"] = item.get("title", "")
        if not item.get("title"):
            item["title"] = item.get("headline", "")

    # Build output
    output = [
        {
            "headline": (item.get("headline") or item.get("title", ""))[:200],
            "url": item.get("url", ""),
            "summary": _strip_markdown(item.get("summary", ""))[:500],
            "published_date": str(item.get("published_date") or item.get("publishedAt") or ""),
            "source": item.get("source") or item.get("source_provider") or "web",
            "symbol": symbol,
            "body": _strip_markdown(item.get("body", "")),
        }
        for item in unique[:max_articles]
        if item.get("headline") or item.get("title")
    ]

    # Persist to DB (fire-and-forget — never blocks)
    _fire_and_forget_db_save(symbol, output)

    # Cache for 1 hour
    cache_news(symbol, output)

    logger.info("get_news_for_symbol(%s): returning %d articles", symbol, len(output))
    return output


def _fire_and_forget_db_save(symbol: str, items: list[dict]) -> None:
    """Save news articles to DB in a fire-and-forget background thread."""
    import threading

    def _save():
        try:
            from apps.nepse_data.models import NewsEvent, Stock
            stock_obj = Stock.objects.filter(symbol=symbol).first()
            for item in items:
                try:
                    NewsEvent.objects.update_or_create(
                        url=item["url"],
                        defaults={
                            "symbol": stock_obj,
                            "headline": (item.get("headline") or "")[:500],
                            "source": (item.get("source") or "web")[:200],
                            "summary": item.get("summary", "")[:2000],
                            "published_date": _parse_date(
                                item.get("published_date") or item.get("publishedAt")
                            ),
                        },
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Error in background db save thread: %s", e)
        finally:
            from django.db import connections
            for conn in connections.all():
                conn.close()

    try:
        thread = threading.Thread(target=_save, daemon=True)
        thread.start()
    except Exception as e:
        logger.warning("_fire_and_forget_db_save(%s) failed to start thread: %s", symbol, e)


def _parse_date(date_str):
    if not date_str:
        return None
    for fmt in (
        "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%B %d, %Y",
        "%d %b %Y", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(str(date_str)[:19], fmt).date()
        except ValueError:
            continue
    return None
