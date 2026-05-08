import asyncio
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')
import django
django.setup()

from services.news_scraper import get_news_for_symbol

async def test():
    news = await get_news_for_symbol('NABIL')
    print(f"News for NABIL: {len(news)} articles")
    for n in news:
        print(f"  [{n.get('source', 'unknown')}] {n.get('headline', '')[:60]}")

if __name__ == '__main__':
    asyncio.run(test())
