import gc
import json
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AmadeusPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "amadeus_careers"

    @property
    def portal_name(self) -> str:
        return "Amadeus Careers (Workday)"

    def _parse_job_postings(self, postings: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for job in postings:
            title = (job.get("title") or "").strip()
            external_path = (job.get("externalPath") or "").strip()
            bullet_fields = job.get("bulletFields") or []
            req_id = bullet_fields[0] if bullet_fields else ""

            job_id = external_path.split("/")[-1] if external_path else (req_id or title)

            if job_id and title and job_id not in seen_ids:
                seen_ids.add(job_id)
                full_link = f"https://amadeus.wd502.myworkdayjobs.com/en-US/jobs{external_path}"
                loc = job.get("locationsText") or "India"
                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=full_link,
                        location=loc,
                    )
                )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        api_url = "https://amadeus.wd502.myworkdayjobs.com/wday/cxs/amadeus/jobs/jobs"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://amadeus.wd502.myworkdayjobs.com/jobs",
            "Origin": "https://amadeus.wd502.myworkdayjobs.com"
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        total_jobs = None

        async with AsyncSession(impersonate="chrome124") as s:
            while True:
                payload = {
                    "appliedFacets": {
                        "locationCountry": ["c4f78be1a8f14da0ab49ce1162348a5e"],
                        "Job_Family_Group": ["7c460db58991017c73f5cf13af1d3474"]
                    },
                    "limit": limit,
                    "offset": offset,
                    "searchText": ""
                }

                resp = await s.post(api_url, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Amadeus Workday API returned {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                if total_jobs is None:
                    total_jobs = data.get("total", 0)

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch_listings = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch_listings)

                if len(postings) < limit or offset + len(postings) >= total_jobs:
                    break

                offset += limit

        logger.info(f"Amadeus curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Amadeus...")
        api_url = "https://amadeus.wd502.myworkdayjobs.com/wday/cxs/amadeus/jobs/jobs"
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
                await page.goto("https://amadeus.wd502.myworkdayjobs.com/jobs", wait_until="domcontentloaded", timeout=30000)

                offset = 0
                limit = 20
                total_jobs = None

                while True:
                    payload = {
                        "appliedFacets": {
                            "locationCountry": ["c4f78be1a8f14da0ab49ce1162348a5e"],
                            "Job_Family_Group": ["7c460db58991017c73f5cf13af1d3474"]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }

                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    method: 'POST',
                                    headers: {{ 'Content-Type': 'application/json', 'Accept': 'application/json' }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)

                    if not isinstance(data, dict) or "jobPostings" not in data:
                        break

                    if total_jobs is None:
                        total_jobs = data.get("total", 0)

                    postings = data.get("jobPostings", [])
                    if not postings:
                        break

                    batch_listings = self._parse_job_postings(postings, seen_ids)
                    listings.extend(batch_listings)

                    if len(postings) < limit or offset + len(postings) >= total_jobs:
                        break

                    offset += limit
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"Amadeus curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
