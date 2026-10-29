import gc
import json
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class CiscoPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "cisco_careers"

    @property
    def portal_name(self) -> str:
        return "Cisco Careers Portal"

    def _parse_jobs(self, jobs: list, seen_ids: Set[str]) -> tuple[List[JobListing], bool]:
        listings = []
        duplicate_found = False
        for job in jobs:
            job_id = str(job.get("jobId") or job.get("jobSeqNo") or "").strip()
            title = str(job.get("title") or "").strip()

            if job_id and title:
                if job_id in seen_ids:
                    duplicate_found = True
                    break

                seen_ids.add(job_id)
                job_link = f"https://careers.cisco.com/global/en/job/{job_id}/"
                loc = job.get("city") or job.get("country") or "India"

                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=job_link,
                        location=loc,
                    )
                )
        return listings, duplicate_found

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        from_offset = 0
        page_size = 100
        max_offset = 2000
        api_url = "https://careers.cisco.com/widgets"

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://careers.cisco.com/global/en/c/product-and-engineering-jobs",
            "Origin": "https://careers.cisco.com",
        }

        async with AsyncSession(impersonate="chrome124") as s:
            while from_offset < max_offset:
                payload = {
                    "sortBy": "",
                    "subsearch": "",
                    "from": from_offset,
                    "jobs": True,
                    "counts": True,
                    "all_fields": ["category", "country", "state", "city"],
                    "pageName": "search-results",
                    "size": page_size,
                    "clearAll": False,
                    "jdsource": "facets",
                    "isSliderEnable": False,
                    "pageId": "page4",
                    "siteType": "external",
                    "keywords": "",
                    "global": True,
                    "selected_fields": {
                        "category": ["Product and Engineering"],
                        "country": ["India"]
                    },
                    "lang": "en_global",
                    "deviceType": "desktop",
                    "country": "global",
                    "refNum": "CISCISGLOBAL",
                    "ddoKey": "refineSearch"
                }

                resp = await s.post(api_url, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Cisco API returned status {resp.status_code} at offset {from_offset}")
                    break

                result = resp.json()
                refine = result.get("refineSearch", {})
                total_hits = refine.get("totalHits", 0)
                jobs = refine.get("data", {}).get("jobs", [])
                if not jobs:
                    break

                new_listings, duplicate_found = self._parse_jobs(jobs, seen_ids)
                listings.extend(new_listings)

                if duplicate_found or len(jobs) < page_size or (total_hits and len(seen_ids) >= total_hits):
                    break

                from_offset += page_size

        logger.info(f"Cisco curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Cisco...")
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
                await page.goto("https://careers.cisco.com/global/en/c/product-and-engineering-jobs", wait_until="domcontentloaded", timeout=30000)

                from_offset = 0
                page_size = 100
                max_offset = 2000
                api_url = "https://careers.cisco.com/widgets"

                while from_offset < max_offset:
                    payload = {
                        "sortBy": "",
                        "subsearch": "",
                        "from": from_offset,
                        "jobs": True,
                        "counts": True,
                        "all_fields": ["category", "country", "state", "city"],
                        "pageName": "search-results",
                        "size": page_size,
                        "clearAll": False,
                        "jdsource": "facets",
                        "isSliderEnable": False,
                        "pageId": "page4",
                        "siteType": "external",
                        "keywords": "",
                        "global": True,
                        "selected_fields": {
                            "category": ["Product and Engineering"],
                            "country": ["India"]
                        },
                        "lang": "en_global",
                        "deviceType": "desktop",
                        "country": "global",
                        "refNum": "CISCISGLOBAL",
                        "ddoKey": "refineSearch"
                    }

                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    method: 'POST',
                                    headers: {{ 'Content-Type': 'application/json' }},
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

                    refine = result.get("refineSearch", {})
                    total_hits = refine.get("totalHits", 0)
                    jobs = refine.get("data", {}).get("jobs", [])
                    if not jobs:
                        break

                    new_listings, duplicate_found = self._parse_jobs(jobs, seen_ids)
                    listings.extend(new_listings)

                    if duplicate_found or len(jobs) < page_size or (total_hits and len(seen_ids) >= total_hits):
                        break

                    from_offset += page_size
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"Cisco curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
