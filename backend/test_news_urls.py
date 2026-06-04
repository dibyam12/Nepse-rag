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
        try:
            print(f"  [{n.get('source', 'unknown')}]")
            print(f"    Headline: {repr(n.get('headline'))}")
            print(f"    URL:      {n.get('url')}")
            print(f"    Summary:  {repr(n.get('summary')[:100])}")
            print(f"    Body:     {repr(n.get('body')[:100]) if n.get('body') else 'None'}")
        except Exception as e:
            print(f"Error printing article details: {e}")

if __name__ == '__main__':
    asyncio.run(test())
