import gc
import logging
import urllib.parse
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MicrosoftPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "microsoft_careers"

    @property
    def portal_name(self) -> str:
        return "Microsoft Careers Portal"

    def _parse_positions(self, positions: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for pos in positions:
            jobid = str(pos.get("displayJobId") or pos.get("id") or "").strip()
            role_name = (pos.get("name") or "").strip()
            pos_url = (pos.get("positionUrl") or "").strip()

            if not jobid or not role_name:
                continue

            if jobid in seen_ids:
                continue
            seen_ids.add(jobid)

            if pos_url.startswith("http"):
                job_listing_link = pos_url
            else:
                job_listing_link = f"https://apply.careers.microsoft.com{pos_url}"

            loc = pos.get("location") or "India"

            listings.append(
                JobListing(
                    jobid=jobid,
                    role_name=role_name,
                    job_listing_link=job_listing_link,
                    location=loc,
                )
            )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        start = 0
        page_size = 10
        max_safety_limit = 200

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://apply.careers.microsoft.com/careers",
        }

        async with AsyncSession(impersonate="chrome124") as s:
            while start < max_safety_limit:
                search_params = {
                    "domain": "microsoft.com",
                    "query": "Software Engineer",
                    "location": "India",
                    "start": str(start),
                    "sort_by": "timestamp",
                    "filter_include_remote": "1",
                    "hl": "en"
                }
                api_query = urllib.parse.urlencode(search_params)
                url = f"https://apply.careers.microsoft.com/api/pcsx/search?{api_query}"

                resp = await s.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Microsoft API returned status {resp.status_code} at start={start}")
                    break

                result = resp.json()
                positions = result.get("data", {}).get("positions", [])
                if not positions:
                    break

                new_listings = self._parse_positions(positions, seen_ids)
                listings.extend(new_listings)

                start += page_size

        logger.info(f"Microsoft curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Microsoft...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                    "--disable-extensions",
                    "--js-flags=--max-old-space-size=128",
                ]
            )
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.route(
                    "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                    lambda route: route.abort()
                )
                await page.goto("https://apply.careers.microsoft.com/careers", wait_until="domcontentloaded", timeout=30000)

                start = 0
                page_size = 10
                max_safety_limit = 200

                while start < max_safety_limit:
                    search_params = {
                        "domain": "microsoft.com",
                        "query": "Software Engineer",
                        "location": "India",
                        "start": str(start),
                        "sort_by": "timestamp",
                        "filter_include_remote": "1",
                        "hl": "en"
                    }
                    api_query = urllib.parse.urlencode(search_params)
                    api_url = f"/api/pcsx/search?{api_query}"

                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch({repr(api_url)});
                                return await response.json();
                            }} catch (err) {{
                                return {{ error: err.message }};
                            }}
                        }}
                    """)

                    if not result or result.get("error"):
                        break

                    positions = result.get("data", {}).get("positions", [])
                    if not positions:
                        break

                    new_listings = self._parse_positions(positions, seen_ids)
                    listings.extend(new_listings)

                    start += page_size
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"Microsoft curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
