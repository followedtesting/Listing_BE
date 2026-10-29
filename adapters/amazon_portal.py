import gc
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AmazonPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "amazon_careers"

    @property
    def portal_name(self) -> str:
        return "Amazon Jobs Portal"

    def _parse_jobs(self, jobs: list, seen_ids: Set[str]) -> tuple[List[JobListing], bool]:
        listings = []
        duplicate_found = False
        for job in jobs:
            job_id = str(job.get("id_icims") or "").strip()
            title = str(job.get("title") or "").strip()
            job_path = str(job.get("job_path") or "").strip()

            if job_id and title:
                if job_id in seen_ids:
                    duplicate_found = True
                    break

                seen_ids.add(job_id)
                full_link = f"https://www.amazon.jobs{job_path}" if job_path.startswith("/") else f"https://www.amazon.jobs/en-gb/jobs/{job_id}"
                loc = job.get("city") or job.get("country_code") or "India"

                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=full_link,
                        location=loc,
                    )
                )
        return listings, duplicate_found

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        page_size = 100
        max_offset = 3000

        headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.amazon.jobs/en-gb/search?category[]=software-development&country[]=IND",
        }

        async with AsyncSession(impersonate="chrome124") as s:
            while offset < max_offset:
                api_url = (
                    f"https://www.amazon.jobs/en-gb/search.json"
                    f"?category%5B%5D=software-development&normalized_country_code%5B%5D=IND"
                    f"&offset={offset}&result_limit={page_size}&sort=recent"
                )
                resp = await s.get(api_url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Amazon API returned status {resp.status_code} at offset {offset}")
                    break

                res_data = resp.json()
                hits = res_data.get("hits", 0)
                jobs = res_data.get("jobs", [])
                if not jobs:
                    break

                new_listings, duplicate_found = self._parse_jobs(jobs, seen_ids)
                listings.extend(new_listings)

                if duplicate_found or len(jobs) < page_size or (hits and len(seen_ids) >= hits):
                    break

                offset += page_size

        logger.info(f"Amazon curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Amazon...")
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
                # Route abort heavy resources
                await page.route(
                    "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                    lambda route: route.abort()
                )
                await page.goto("https://www.amazon.jobs/en-gb/search", wait_until="domcontentloaded", timeout=30000)

                offset = 0
                page_size = 100
                max_offset = 3000

                while offset < max_offset:
                    api_url = (
                        f"https://www.amazon.jobs/en-gb/search.json"
                        f"?category%5B%5D=software-development&normalized_country_code%5B%5D=IND"
                        f"&offset={offset}&result_limit={page_size}&sort=recent"
                    )
                    res_data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    headers: {{ 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }}
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)

                    if not res_data or res_data.get("error"):
                        break

                    hits = res_data.get("hits", 0)
                    jobs = res_data.get("jobs", [])
                    if not jobs:
                        break

                    new_listings, duplicate_found = self._parse_jobs(jobs, seen_ids)
                    listings.extend(new_listings)

                    if duplicate_found or len(jobs) < page_size or (hits and len(seen_ids) >= hits):
                        break

                    offset += page_size
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"Amazon curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
