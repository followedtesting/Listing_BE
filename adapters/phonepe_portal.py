import gc
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PhonePePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "phonepe_careers"

    @property
    def portal_name(self) -> str:
        return "PhonePe Careers"

    def _parse_results(self, results: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for job in results:
            dept = str(job.get("department", "")).strip()
            apply_url = job.get("applyUrl")
            title = str(job.get("title", "")).strip()

            if dept.lower() == "engineering" and apply_url and title:
                apply_url_str = str(apply_url).strip()
                parts = apply_url_str.rstrip("/").split("/")
                job_id = parts[-1] if parts else apply_url_str

                if job_id and job_id not in seen_ids:
                    seen_ids.add(job_id)
                    loc = job.get("location") or "India"
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=apply_url_str,
                            location=loc,
                        )
                    )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        json_url = "https://www.phonepe.com/apollo/job-postings/latest.json"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.phonepe.com/careers/job-openings/",
        }

        seen_ids: Set[str] = set()
        async with AsyncSession(impersonate="chrome124") as s:
            resp = await s.get(json_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"PhonePe JSON endpoint returned {resp.status_code}")
                return []

            api_data = resp.json()
            results = api_data.get("results", []) if isinstance(api_data, dict) else []
            listings = self._parse_results(results, seen_ids)

        logger.info(f"PhonePe curl scraped {len(listings)} engineering jobs.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for PhonePe...")
        target_url = "https://www.phonepe.com/careers/job-openings/"
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
                await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

                json_url = "https://www.phonepe.com/apollo/job-postings/latest.json"
                api_data = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const response = await fetch('{json_url}');
                            return await response.json();
                        }} catch (err) {{
                            return {{ "error": err.message }};
                        }}
                    }}
                """)

                if isinstance(api_data, dict) and "results" in api_data:
                    results = api_data.get("results", [])
                    listings = self._parse_results(results, seen_ids)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"PhonePe curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
