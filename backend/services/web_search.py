# services/web_search.py (UPDATED FOR REALITY)
"""
Web search fallback chain — based on what ACTUALLY WORKS.
Primary: NewsAPI (working, dedicated news, good metadata)
Fallback 1: DuckDuckGo (free, unlimited)
Fallback 2: (Placeholder for future Google CSE fix)
Fallback 3: (Placeholder for future SerpAPI fresh credits)
"""

import httpx
import logging
import os
from django.core.cache import cache
import asyncio
from decouple import config

logger = logging.getLogger('nepse_rag')

# ═══════════════════════════════════════════════════════════════
# PRIMARY: NEWSAPI (WORKING)
# ═══════════════════════════════════════════════════════════════

async def newsapi_search(query: str, count: int = 5) -> list[dict]:
    """
    NewsAPI.org — PRIMARY provider (actually working).
    Free tier: 500 requests/month (~16/day).
    
    Returns metadata-rich articles:
    {title, url, description, publishedAt, source.name, source.id}
    """
    api_key = config('NEWSAPI_KEY', default='')
    
    if not api_key or api_key == 'your_newsapi_key_here':
        logger.warning("NewsAPI: key not configured")
        return []
    
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            'q': query,
            'apiKey': api_key,
            'pageSize': count,
            'sortBy': 'publishedAt',
            'language': 'en'
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10)
        
        if resp.status_code != 200:
            logger.warning(f"NewsAPI: HTTP {resp.status_code}")
            return []
        
        data = resp.json()
        
        if data.get('status') != 'ok':
            logger.warning(f"NewsAPI: {data.get('message', 'unknown error')}")
            return []
        
        articles = data.get('articles', [])
        
        if not articles:
            logger.debug("NewsAPI: no articles found")
            return []
        
        logger.info(f"NewsAPI: {len(articles)} articles returned")
        return [
            {
                'title': a.get('title', '')[:500],
                'url': a.get('url', ''),
                'snippet': a.get('description', ''),
                'publishedAt': a.get('publishedAt'),
                'source': a.get('source', {}).get('name', ''),
                'source_provider': 'newsapi'
            }
            for a in articles
        ]
    
    except Exception as e:
        logger.error(f"NewsAPI error: {e}")
        return []

# NEPSE-specific financial news sites (mirrors Google CSE config)
NEPSE_SITES = [
    "sharesansar.com",
    "merolagani.com",
    "nepsealpha.com",
    "sharehubnepal.com",
    "nepalipaisa.com",
    "bajarkochirfar.com",
    "nepalytix.com",
    "moneymitra.com",
]

async def duckduckgo_search(query: str, count: int = 5) -> list[dict]:
    """
    DuckDuckGo fallback — free, unlimited.
    Uses the new `ddgs` package (successor to duckduckgo_search).
    
    Strategy:
    1. First searches NEPSE-specific financial sites using site: operator
    2. If not enough results, supplements with a general search
    """
    try:
        from ddgs import DDGS
        
        logger.debug(f"DuckDuckGo: searching '{query}'")
        
        loop = asyncio.get_event_loop()
        
        def _search():
            ddgs = DDGS()
            all_results = []
            seen_urls = set()
            
            # Step 1: Search NEPSE-specific sites first
            site_filter = " OR ".join(f"site:{s}" for s in NEPSE_SITES)
            site_query = f"{query} ({site_filter})"
            
            try:
                site_results = list(ddgs.news(site_query, max_results=count))
                for r in site_results:
                    url = r.get('url', r.get('href', ''))
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
                if all_results:
                    logger.debug(f"DuckDuckGo: {len(all_results)} results from NEPSE sites")
            except Exception as e:
                logger.debug(f"DuckDuckGo site-restricted news failed: {e}")
                # Try text search with site filter instead
                try:
                    site_results = list(ddgs.text(site_query, max_results=count))
                    for r in site_results:
                        url = r.get('url', r.get('href', ''))
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append(r)
                except Exception as e2:
                    logger.debug(f"DuckDuckGo site-restricted text failed: {e2}")
            
            # Step 2: If not enough results, do a general search
            if len(all_results) < count:
                remaining = count - len(all_results)
                try:
                    general = list(ddgs.news(query, max_results=remaining))
                    for r in general:
                        url = r.get('url', r.get('href', ''))
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append(r)
                except Exception as e:
                    logger.debug(f"DuckDuckGo general news failed: {e}")
                    try:
                        general = list(ddgs.text(query, max_results=remaining))
                        for r in general:
                            url = r.get('url', r.get('href', ''))
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                all_results.append(r)
                    except Exception as e2:
                        logger.debug(f"DuckDuckGo general text failed: {e2}")
            
            return all_results
        
        results = await loop.run_in_executor(None, _search)
        
        if not results:
            logger.debug("DuckDuckGo: no results (may be IP rate-limited)")
            return []
        
        logger.info(f"DuckDuckGo: {len(results)} results")
        return [
            {
                'title': r.get('title', '')[:500],
                'url': r.get('url', r.get('href', r.get('link', ''))),
                'snippet': r.get('body', '')[:500],
                'publishedAt': r.get('date'),
                'source': r.get('source', 'DuckDuckGo'),
                'source_provider': 'duckduckgo'
            }
            for r in results
        ]
    
    except ImportError:
        logger.warning("DuckDuckGo: ddgs package not installed. Run: pip install ddgs")
        return []
    except Exception as e:
        logger.debug(f"DuckDuckGo error: {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# PLACEHOLDER: Google Custom Search (Currently 403)
# ═══════════════════════════════════════════════════════════════

async def google_custom_search(query: str, count: int = 5) -> list[dict]:
    """
    Google Custom Search — TEMPORARILY DISABLED (403 error).
    
    To fix:
    1. Go to console.cloud.google.com
    2. Verify "Custom Search API" is ENABLED
    3. Verify API key is correct
    4. Verify Search Engine ID is correct
    5. Update .env with correct values
    6. Uncomment this code below
    """
    logger.debug("Google CSE: skipped (403 error from previous attempts)")
    return []

# ═══════════════════════════════════════════════════════════════
# PLACEHOLDER: SerpAPI (Currently 429 - No Credits)
# ═══════════════════════════════════════════════════════════════

async def serpapi_search(query: str, count: int = 5) -> list[dict]:
    """
    SerpAPI — TEMPORARILY DISABLED (429 rate limit / no credits).
    
    To fix:
    1. Go to https://serpapi.com/
    2. Create a NEW account (get fresh $100 free credits)
    3. Copy the new API key
    4. Update .env: SERPAPI_KEY=new_key
    5. Uncomment this code below
    """
    logger.debug("SerpAPI: skipped (429 rate limit from previous account)")
    return []

# ═══════════════════════════════════════════════════════════════
# MAIN UNIFIED FUNCTION
# ═══════════════════════════════════════════════════════════════

async def web_search(query: str, count: int = 5) -> list[dict]:
    """
    Web search with pragmatic fallback chain.
    
    Priority 1: NewsAPI (working, reliable, good metadata)
    Priority 2: DuckDuckGo (free fallback)
    Priority 3: (Reserved for Google CSE once 403 is fixed)
    Priority 4: (Reserved for SerpAPI once fresh credits obtained)
    
    Returns list of {title, url, snippet, publishedAt, source, source_provider}.
    """
    
    logger.info(f"web_search: '{query}'")
    
    # Priority 1: NewsAPI (PRIMARY - WORKING)
    results = await newsapi_search(query, count)
    if results:
        logger.info(f"web_search: using NewsAPI ({len(results)} results)")
        return results
    
    # Priority 2: DuckDuckGo (FREE FALLBACK)
    results = await duckduckgo_search(query, count)
    if results:
        logger.info(f"web_search: using DuckDuckGo fallback ({len(results)} results)")
        return results
    
    # All failed
    logger.error(f"web_search: all providers failed for '{query}'")
    return []

# ═══════════════════════════════════════════════════════════════
# FETCH ARTICLE
# ═══════════════════════════════════════════════════════════════

async def fetch_article(url: str, max_chars: int = 2000) -> str:
    """
    Fetches a URL and extracts clean text.
    Returns empty string on any error.
    """
    if not url:
        return ""
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/120.0.0.0 Safari/537.36'
                },
                follow_redirects=True
            )
        
        if resp.status_code != 200:
            return ""
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Remove junk
        for tag in soup(['script', 'style', 'nav', 'footer', 'ads', 'noscript']):
            tag.decompose()
        
        # Get main content
        main = soup.find('main') or soup.find('article') or soup.find('body')
        if not main:
            return ""
        
        text = main.get_text(separator=' ', strip=True)
        
        # Clean whitespace
        import re
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text[:max_chars]
    
    except Exception as e:
        logger.debug(f"fetch_article error: {e}")
        return ""
