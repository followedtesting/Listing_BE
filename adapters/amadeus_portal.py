import gc
import json
import logging
from typing import List, Set, Dict, Any
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class AmadeusPortalAdapter(BaseJobAdapter):
    """
    Adapter for Amadeus Careers (Workday platform).
    Target URL: https://amadeus.wd502.myworkdayjobs.com/jobs?locationCountry=c4f78be1a8f14da0ab49ce1162348a5e

    Filters:
      - Country: India (locationCountry=c4f78be1a8f14da0ab49ce1162348a5e)

    Network & Platform Architecture:
      - Platform: Workday CXS API (`/wday/cxs/amadeus/jobs/jobs`)
      - Endpoint: POST https://amadeus.wd502.myworkdayjobs.com/wday/cxs/amadeus/jobs/jobs
      - Primary Extraction: High-performance HTTP POST via curl_cffi AsyncSession with Chrome impersonation.
      - Secondary Fallback: Headless Playwright browser automation with in-page fetch evaluation.
    """

    TARGET_URL = "https://amadeus.wd502.myworkdayjobs.com/jobs?locationCountry=c4f78be1a8f14da0ab49ce1162348a5e"
    BASE_URL = "https://amadeus.wd502.myworkdayjobs.com"
    API_URL = "https://amadeus.wd502.myworkdayjobs.com/wday/cxs/amadeus/jobs/jobs"

    LOCATION_COUNTRY_ID = "c4f78be1a8f14da0ab49ce1162348a5e"
    LIMIT = 20

    @property
    def portal_id(self) -> str:
        return "amadeus_careers"

    @property
    def portal_name(self) -> str:
        return "Amadeus Careers (Workday)"

    def _normalize_location(self, raw_loc: str) -> str:
        """Normalizes location string to ensure India is appended if needed."""
        loc = raw_loc.strip()
        if not loc:
            return "India"
        if "india" not in loc.lower():
            return f"{loc}, India"
        return loc

    def _parse_job_postings(self, postings: list, seen_ids: Set[str]) -> List[JobListing]:
        """Parses Workday job postings into JobListing models."""
        listings = []
        for job in postings:
            title = (job.get("title") or "").strip()
            external_path = (job.get("externalPath") or "").strip()
            bullet_fields = job.get("bulletFields") or []
            req_id = bullet_fields[0] if bullet_fields else ""

            job_id = external_path.split("/")[-1] if external_path else (req_id or title)

            if job_id and title and job_id not in seen_ids:
                seen_ids.add(job_id)
                full_link = f"{self.BASE_URL}/en-US/jobs{external_path}"
                raw_loc = job.get("locationsText") or "India"
                location = self._normalize_location(raw_loc)

                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=full_link,
                        location=location,
                    )
                )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes Workday CXS API via high-performance curl_cffi AsyncSession."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": self.TARGET_URL,
            "Origin": self.BASE_URL,
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        total_jobs = None

        async with AsyncSession(impersonate="chrome124") as s:
            while True:
                payload = {
                    "appliedFacets": {
                        "locationCountry": [self.LOCATION_COUNTRY_ID],
                    },
                    "limit": self.LIMIT,
                    "offset": offset,
                    "searchText": "",
                }

                resp = await s.post(self.API_URL, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(
                        f"[{self.portal_id}] Amadeus Workday API returned {resp.status_code} at offset {offset}"
                    )
                    break

                data = resp.json()
                if total_jobs is None:
                    total_jobs = data.get("total", 0)

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch_listings = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch_listings)

                if len(postings) < self.LIMIT or offset + len(postings) >= total_jobs:
                    break

                offset += self.LIMIT

        logger.info(f"[{self.portal_id}] Amadeus curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Secondary fallback: Scrapes via headless Playwright browser."""
        logger.info(f"[{self.portal_id}] Falling back to Playwright (low-RAM) for Amadeus...")
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
                ],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                page = await context.new_page()
                await page.route(
                    "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                    lambda route: route.abort(),
                )
                await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=30000)

                offset = 0
                total_jobs = None

                while True:
                    payload = {
                        "appliedFacets": {
                            "locationCountry": [self.LOCATION_COUNTRY_ID],
                        },
                        "limit": self.LIMIT,
                        "offset": offset,
                        "searchText": "",
                    }

                    data = await page.evaluate(
                        f"""
                        async () => {{
                            try {{
                                const response = await fetch('{self.API_URL}', {{
                                    method: 'POST',
                                    headers: {{ 'Content-Type': 'application/json', 'Accept': 'application/json' }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """
                    )

                    if not isinstance(data, dict) or "jobPostings" not in data:
                        break

                    if total_jobs is None:
                        total_jobs = data.get("total", 0)

                    postings = data.get("jobPostings", [])
                    if not postings:
                        break

                    batch_listings = self._parse_job_postings(postings, seen_ids)
                    listings.extend(batch_listings)

                    if len(postings) < self.LIMIT or offset + len(postings) >= total_jobs:
                        break

                    offset += self.LIMIT
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        """Main scraping entrypoint: tries curl_cffi first, falls back to Playwright."""
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(
                f"[{self.portal_id}] Amadeus curl scraping error: {e}. Falling back to Playwright..."
            )

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
