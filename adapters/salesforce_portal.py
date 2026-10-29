import gc
import json
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SalesforcePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "salesforce_careers"

    @property
    def portal_name(self) -> str:
        return "Salesforce Careers Portal"

    def _parse_job_postings(self, job_postings: list, seen_ids: Set[str]) -> tuple[List[JobListing], bool]:
        listings = []
        duplicate_found = False
        for job in job_postings:
            title = (job.get("title") or "").strip()
            ext_path = (job.get("externalPath") or "").strip()
            bullet_fields = job.get("bulletFields") or []

            jobid = ""
            if bullet_fields and len(bullet_fields) > 0:
                jobid = str(bullet_fields[0]).strip()

            if not jobid:
                if "_" in ext_path:
                    jobid = ext_path.split("_")[-1]
                else:
                    jobid = ext_path.split("/")[-1]

            if not jobid or not title:
                continue

            if jobid in seen_ids:
                duplicate_found = True
                break

            seen_ids.add(jobid)

            if ext_path.startswith("http"):
                job_listing_link = ext_path
            else:
                job_listing_link = f"https://salesforce.wd12.myworkdayjobs.com/External_Career_Site{ext_path}"

            loc = job.get("locationsText") or "India"

            listings.append(
                JobListing(
                    jobid=jobid.strip(),
                    role_name=title.strip(),
                    job_listing_link=job_listing_link.strip(),
                    location=loc,
                )
            )
        return listings, duplicate_found

    async def _scrape_curl(self) -> List[JobListing]:
        api_url = "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/jobs"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site",
            "Origin": "https://salesforce.wd12.myworkdayjobs.com"
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        max_safety_limit = 200

        async with AsyncSession(impersonate="chrome124") as s:
            while offset < max_safety_limit:
                payload = {
                    "appliedFacets": {
                        "CF_-_REC_-_LRV_-_Job_Posting_Anchor_-_Country_from_Job_Posting_Location_Extended": ["c4f78be1a8f14da0ab49ce1162348a5e"],
                        "jobFamilyGroup": ["14fa3452ec7c1011f90d0002a2100000"]
                    },
                    "limit": limit,
                    "offset": offset,
                    "searchText": ""
                }

                resp = await s.post(api_url, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Salesforce Workday API returned {resp.status_code} at offset {offset}")
                    break

                result = resp.json()
                job_postings = result.get("jobPostings", [])
                if not job_postings:
                    break

                new_listings, duplicate_found = self._parse_job_postings(job_postings, seen_ids)
                listings.extend(new_listings)

                if duplicate_found or len(job_postings) < limit:
                    break

                offset += limit

        logger.info(f"Salesforce curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Salesforce...")
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
                await page.goto("https://salesforce.wd12.myworkdayjobs.com/External_Career_Site", wait_until="domcontentloaded", timeout=30000)

                offset = 0
                limit = 20
                max_safety_limit = 200

                while offset < max_safety_limit:
                    payload = {
                        "appliedFacets": {
                            "CF_-_REC_-_LRV_-_Job_Posting_Anchor_-_Country_from_Job_Posting_Location_Extended": ["c4f78be1a8f14da0ab49ce1162348a5e"],
                            "jobFamilyGroup": ["14fa3452ec7c1011f90d0002a2100000"]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }

                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('/wday/cxs/salesforce/External_Career_Site/jobs', {{
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

                    if not result or "error" in result:
                        break

                    job_postings = result.get("jobPostings", [])
                    if not job_postings:
                        break

                    new_listings, duplicate_found = self._parse_job_postings(job_postings, seen_ids)
                    listings.extend(new_listings)

                    if duplicate_found or len(job_postings) < limit:
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
            logger.warning(f"Salesforce curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
