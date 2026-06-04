import asyncio
import httpx
from bs4 import BeautifulSoup

async def main():
    url = "https://www.sharesansar.com/newsdetail/capital-plan-of-commercial-bank"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Let's find some paragraphs or divs that might contain the news content
            print("Title:", soup.find('title').text)
            # Find divs with class names containing 'news' or 'post' or 'content'
            divs = soup.find_all('div')
            classes = set()
            for d in divs:
                cls = d.get('class')
                if cls:
                    for c in cls:
                        if 'news' in c or 'post' in c or 'detail' in c or 'content' in c:
                            classes.add(c)
            print("Found classes containing news/post/detail/content:", sorted(list(classes)))
            
            # Let's print out the first 500 chars of some specific divs to find the content
            for cls in ['news-detail', 'post-content', 'news-content', 'post-body', 'news-detail-content']:
                el = soup.select_one('.' + cls)
                if el:
                    print(f"\nDiv .{cls} text preview:")
                    print(el.get_text(strip=True)[:200])
        else:
            print("Failed to fetch page, status:", resp.status_code)

asyncio.run(main())
