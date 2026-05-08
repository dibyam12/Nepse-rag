import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')
sys.stdout.reconfigure(encoding='utf-8')
import django
django.setup()

import asyncio
from services.web_search import duckduckgo_search

SYMBOLS = ["NABIL", "NICA", "SBL", "HIDCL", "NLIC"]

async def test():
    for symbol in SYMBOLS:
        query = f"{symbol} Nepal stock news"
        results = await duckduckgo_search(query, 3)
        print(f"\n{'='*50}")
        print(f"  {symbol} -- {len(results)} results")
        print(f"{'='*50}")
        for r in results:
            print(f"  [{r.get('source', '?')}] {r['title'][:60]}")
            print(f"    {r['url'][:80]}")
        if not results:
            print("  (no results)")
        # Small delay to avoid rate-limiting
        await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(test())
