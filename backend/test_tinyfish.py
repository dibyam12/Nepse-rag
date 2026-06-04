"""
Test 2: DDG news-focused queries + Tinyfish — verify we get actual articles
"""
import asyncio
import re
import httpx
from ddgs import DDGS

TINYFISH_API_KEY = "TINYFISH_API_KEY_PLACEHOLDER"
TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _ddg_news_search(query: str, max_results: int = 5) -> list[dict]:
    """Try .news() first, fallback to .text() with timelimit."""
    results = []
    seen = set()
    try:
        with DDGS() as ddgs:
            # Try news endpoint first
            try:
                for item in ddgs.news(query, max_results=max_results, timelimit="m"):
                    url = item.get("url", item.get("href", ""))
                    if url and url not in seen:
                        seen.add(url)
                        results.append({
                            "title": item.get("title", ""),
                            "url": url,
                            "snippet": item.get("body", "")[:200],
                            "date": item.get("date", ""),
                            "source": item.get("source", ""),
                        })
            except Exception as e:
                print(f"  ddgs.news() failed: {e}")

            # Fallback to text() if news gave nothing
            if not results:
                try:
                    for item in ddgs.text(query, max_results=max_results, timelimit="m"):
                        url = item.get("href", item.get("url", ""))
                        if url and url not in seen:
                            seen.add(url)
                            results.append({
                                "title": item.get("title", ""),
                                "url": url,
                                "snippet": item.get("body", "")[:200],
                            })
                except Exception as e:
                    print(f"  ddgs.text() failed: {e}")
    except Exception as e:
        print(f"DDGS init failed: {e}")
    return results


async def _fetch_tinyfish(client: httpx.AsyncClient, url: str) -> dict:
    """Fetch page via Tinyfish, return {text, title}."""
    try:
        resp = await client.post(
            TINYFISH_FETCH_URL,
            json={"urls": [url], "format": "markdown"},
            headers={
                "X-API-Key": TINYFISH_API_KEY,
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return {"text": "", "title": ""}
        r = results[0]
        text = _clean_text(str(r.get("text", "")))[:2000]
        title = str(r.get("title", "")).strip()
        return {"text": text, "title": title}
    except Exception as e:
        print(f"  Tinyfish error for {url}: {e}")
        return {"text": "", "title": ""}


async def main():
    # Test multi-site news queries like ddg_search_multi_site does
    queries = [
        '"NABIL" OR "Nabil Bank" site:sharesansar.com',
        '"NABIL" OR "Nabil Bank" site:merolagani.com',
        "NABIL Nepal stock news",
    ]

    all_hits = []
    for q in queries:
        print(f"\nDDG query: {q}")
        hits = await asyncio.to_thread(_ddg_news_search, q, 3)
        print(f"  {len(hits)} results")
        for h in hits:
            print(f"    {h['title'][:60]} | {h['url'][:70]}")
        all_hits.extend(hits)

    # Deduplicate
    seen = set()
    unique = []
    for h in all_hits:
        if h["url"] not in seen:
            seen.add(h["url"])
            unique.append(h)

    print(f"\n{'='*60}")
    print(f"Total unique hits: {len(unique)}")

    # Fetch content for first 4 articles via Tinyfish
    to_fetch = unique[:4]
    print(f"Fetching {len(to_fetch)} articles via Tinyfish...")

    async with httpx.AsyncClient(
        timeout=30,
        limits=httpx.Limits(max_connections=10),
    ) as client:
        fetched = await asyncio.gather(
            *[_fetch_tinyfish(client, h["url"]) for h in to_fetch]
        )

    for hit, content in zip(to_fetch, fetched):
        print(f"\n{'='*60}")
        print(f"DDG Title:  {hit['title'][:80]}")
        print(f"Page Title: {content['title'][:80]}")
        print(f"URL:        {hit['url']}")
        preview = content['text'][:400] if content['text'] else '(empty)'
        print(f"Content:    {preview}")


if __name__ == "__main__":
    asyncio.run(main())
