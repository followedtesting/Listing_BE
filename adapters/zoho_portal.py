import logging
import asyncio
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ZohoPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "zoho_careers"

    @property
    def portal_name(self) -> str:
        return "Zoho Careers Portal"

    def _parse_jobs(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for j in jobs:
            job_id = j.get("id") or j.get("id_id") or j.get("Job_Opening_ID")
            title = (j.get("Posting_Title") or j.get("Job_Opening_Name") or "").strip()

            if not job_id or not title or str(job_id) in seen_ids:
                continue

            seen_ids.add(str(job_id))

            city = j.get("City", "").strip() if j.get("City") else ""
            state = j.get("State", "").strip() if j.get("State") else ""
            country = j.get("Country") or j.get("Country1") or ""
            if isinstance(country, str):
                country = country.strip()
            else:
                country = ""

            loc_parts = [p for p in [city, state, country] if p]
            location = ", ".join(loc_parts) if loc_parts else "India"

            job_link = j.get("$url", "").strip()
            if not job_link:
                job_link = f"https://careers.zohocorp.com/jobs/Careers/{job_id}"

            listings.append(JobListing(
                jobid=str(job_id),
                role_name=title,
                job_listing_link=job_link,
                location=location
            ))
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        endpoints = [
            "https://careers.zohocorp.com/recruit/v2/public/Job_Openings?pagename=Careers&source=CareerSite",
            "https://zohoapac.zohorecruit.in/recruit/v2/public/Job_Openings?pagename=Careers&source=CareerSite",
            "https://careers.zohorecruit.in/recruit/v2/public/Job_Openings?pagename=Careers&source=CareerSite",
        ]

        listings = []
        seen_ids = set()

        async with AsyncSession(impersonate="chrome124") as s:
            for url in endpoints:
                try:
                    logger.info(f"Fetching Zoho jobs from API endpoint: {url}")
                    res = await s.get(url, headers=headers, timeout=15)
                    if res.status_code == 200:
                        data = res.json()
                        jobs = data.get("data", [])
                        parsed = self._parse_jobs(jobs, seen_ids)
                        listings.extend(parsed)
                    else:
                        logger.warning(f"Zoho API {url} returned status code {res.status_code}")
                except Exception as e:
                    logger.warning(f"Error requesting Zoho API {url}: {e}")

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Zoho scrape via Playwright browser session fallback...")
        listings = []
        seen_ids = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()

                endpoints = [
                    "https://careers.zohocorp.com/recruit/v2/public/Job_Openings?pagename=Careers&source=CareerSite",
                    "https://zohoapac.zohorecruit.in/recruit/v2/public/Job_Openings?pagename=Careers&source=CareerSite",
                ]

                try:
                    await page.goto("https://www.zoho.com/careers/", wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    logger.warning(f"Playwright navigation warning on Zoho careers landing page: {e}")

                for api_url in endpoints:
                    data = await page.evaluate(f"""async () => {{
                        try {{
                            let res = await fetch('{api_url}');
                            if (!res.ok) return null;
                            return await res.json();
                        }} catch(e) {{
                            return null;
                        }}
                    }}""")

                    if data and isinstance(data, dict):
                        jobs = data.get("data", [])
                        parsed = self._parse_jobs(jobs, seen_ids)
                        listings.extend(parsed)

            except Exception as pe:
                logger.error(f"Playwright fallback failed for Zoho: {pe}")
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Finished Zoho Careers HTTP scrape. Found {len(listings)} listings.")
                return listings
        except Exception as e:
            logger.warning(f"Zoho HTTP scrape failed: {e}. Trying Playwright fallback...")

        try:
            listings = await self._scrape_playwright()
            logger.info(f"Finished Zoho Careers Playwright fallback scrape. Found {len(listings)} listings.")
            return listings
        except Exception as e:
            logger.error(f"Error in Zoho portal Playwright fallback: {e}", exc_info=True)
            return []
