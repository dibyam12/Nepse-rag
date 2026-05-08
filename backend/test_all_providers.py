import os
import sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')
sys.stdout.reconfigure(encoding='utf-8')
import django
django.setup()

import asyncio
from services.web_search import (
    newsapi_search,
    duckduckgo_search,
    google_custom_search,
    serpapi_search,
)

async def test_all():
    print("=" * 60)
    print("  NEPSE Web Search - Provider Status Report")
    print("=" * 60)

    print("\n--- 1. NewsAPI (PRIMARY) ---")
    r1 = await newsapi_search("NABIL Bank Nepal news", 2)
    status1 = f"WORKING ({len(r1)} results)" if r1 else "FAILED (0 results)"
    print(f"  Status: {status1}")
    for r in r1:
        print(f"    [{r.get('source','')}] {r['title'][:55]}")

    print("\n--- 2. DuckDuckGo (FALLBACK) ---")
    r2 = await duckduckgo_search("NABIL Bank Nepal news", 2)
    status2 = f"WORKING ({len(r2)} results)" if r2 else "FAILED (0 results)"
    print(f"  Status: {status2}")
    for r in r2:
        print(f"    [{r.get('source','')}] {r['title'][:55]}")

    print("\n--- 3. Google CSE (DISABLED) ---")
    r3 = await google_custom_search("NABIL Bank Nepal news", 2)
    status3 = f"WORKING ({len(r3)} results)" if r3 else "DISABLED (placeholder)"
    print(f"  Status: {status3}")

    print("\n--- 4. SerpAPI (DISABLED) ---")
    r4 = await serpapi_search("NABIL Bank Nepal news", 2)
    status4 = f"WORKING ({len(r4)} results)" if r4 else "DISABLED (placeholder)"
    print(f"  Status: {status4}")

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  NewsAPI:    {status1}")
    print(f"  DuckDuckGo: {status2}")
    print(f"  Google CSE: {status3}")
    print(f"  SerpAPI:    {status4}")
    working = sum(1 for s in [status1, status2, status3, status4] if "WORKING" in s)
    print(f"\n  Active providers: {working}/4")
    print("=" * 60)

if __name__ == '__main__':
    asyncio.run(test_all())
