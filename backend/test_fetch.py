import asyncio
import httpx

async def main():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html, */*",
        "X-Requested-With": "XMLHttpRequest"
    }
    url = "https://www.sharesansar.com/newslist?symbol=NABIL"
    print(f"Fetching {url}...")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            print(f"Status: {resp.status_code}")
            print(f"Response length: {len(resp.text)}")
            print(f"Preview: {resp.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())
