import asyncio
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')
import django
django.setup()

from services.web_search import google_custom_search

async def test():
    results = await google_custom_search("NABIL Bank Nepal news", 5)
    print(f"Google CSE: {len(results)} results")
    for r in results:
        print(f"  - {r['title'][:70]}")

if __name__ == "__main__":
    asyncio.run(test())
