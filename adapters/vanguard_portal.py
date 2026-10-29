import asyncio
import gc
import logging
from typing import List, Set, Optional, Dict, Any
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class VanguardPortalAdapter(BaseJobAdapter):
    """
    Adapter for Vanguard Careers Portal (M-Cloud / Google Cloud Talent Solution).
    Target URL: https://www.vanguardjobs.com/job-search-results/?location=IN%2C%20Telangana%2C%20Hyderabad&category[]=Data%20%26%20analytics&category[]=Technology
    Filters: Location: Hyderabad, Telangana, India; Categories: Data & analytics, Technology
    """

    TARGET_PAGE_URL = (
        "https://www.vanguardjobs.com/job-search-results/"
        "?location=IN%2C%20Telangana%2C%20Hyderabad&category[]=Data%20%26%20analytics&category[]=Technology"
    )

    API_URL = "https://jobsapi-google.m-cloud.io/api/job/search"
    COMPANY_NAME = "companies/fbd5ce04-22d1-4aae-90dc-0282e45ee06f"
    CUSTOM_ATTRIBUTE_FILTER = (
        '(primary_category="Data & analytics" OR primary_category="Technology") '
        'AND is_internal="External" '
        'AND (country_state_city="IN, Telangana, Hyderabad")'
    )

    @property
    def portal_id(self) -> str:
        return "vanguard_careers"

    @property
    def portal_name(self) -> str:
        return "Vanguard Careers Portal"

    def _parse_job_item(self, item: Dict[str, Any], seen_ids: Set[str]) -> Optional[JobListing]:
        """Parse a single search result item from M-Cloud API response."""
        job = item.get("job") or {}
        job_id = str(job.get("ref") or job.get("id") or "").strip()
        title = (job.get("title") or "").strip()
        if not job_id or not title or job_id in seen_ids:
            return None

        # Build clean absolute link
        url = (job.get("url") or "").strip()
        if url.startswith("http://"):
            url = "https://" + url[7:]
        elif not url.startswith("http"):
            url = f"https://www.vanguardjobs.com{url}"

        # Location extraction
        loc = "Hyderabad, India"
        locs = job.get("google_locations") or []
        if locs and isinstance(locs, list) and isinstance(locs[0], dict):
            city = locs[0].get("city") or "Hyderabad"
            country = locs[0].get("country") or "IN"
            loc = f"{city}, {country}".strip(", ")

        seen_ids.add(job_id)
        return JobListing(
            jobid=job_id,
            role_name=title,
            job_listing_link=url,
            location=loc,
        )

    async def _scrape_curl(self) -> List[JobListing]:
        seen_ids: Set[str] = set()
        listings: List[JobListing] = []

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.vanguardjobs.com",
            "Referer": self.TARGET_PAGE_URL,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        offset = 0
        page_size = 100

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                params = {
                    "pageSize": str(page_size),
                    "offset": str(offset),
                    "companyName": self.COMPANY_NAME,
                    "customAttributeFilter": self.CUSTOM_ATTRIBUTE_FILTER,
                    "orderBy": "posting_publish_time desc",
                }

                resp = await session.get(self.API_URL, params=params, headers=headers, timeout=25)
                if resp.status_code != 200:
                    logger.warning(f"Vanguard API returned HTTP {resp.status_code}: {resp.text[:200]}")
                    break

                try:
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Failed to parse Vanguard API JSON: {e}")
                    break

                search_results = data.get("searchResults") or []
                if not search_results:
                    break

                for item in search_results:
                    listing = self._parse_job_item(item, seen_ids)
                    if listing:
                        listings.append(listing)

                total_hits = data.get("totalHits") or 0
                offset += len(search_results)
                if offset >= total_hits or len(search_results) < page_size:
                    break

        logger.info(f"Vanguard curl scraped {len(listings)} jobs.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Vanguard careers scraping via Playwright fallback...")
        seen_ids: Set[str] = set()
        listings: List[JobListing] = []
        captured_api_jobs: List[Dict[str, Any]] = []
        playwright_obj = None
        browser = None

        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
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
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort()
            )

            # Intercept M-Cloud responses
            async def handle_response(response):
                if "jobsapi-google.m-cloud.io/api/job/search" in response.url:
                    try:
                        json_data = await response.json()
                        results = json_data.get("searchResults") or []
                        captured_api_jobs.extend(results)
                    except Exception:
                        pass

            page.on("response", handle_response)

            await page.goto(self.TARGET_PAGE_URL, wait_until="networkidle", timeout=45000)
            await asyncio.sleep(3)

            # 1. Process captured API responses if any
            if captured_api_jobs:
                for item in captured_api_jobs:
                    listing = self._parse_job_item(item, seen_ids)
                    if listing:
                        listings.append(listing)

            # 2. If no jobs captured from API, extract from DOM
            if not listings:
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                job_links = soup.select("a[href*='/job/']")
                for a in job_links:
                    href = (a.get("href") or "").strip()
                    title = a.get_text(strip=True)
                    if not href or not title:
                        continue

                    import re
                    m = re.search(r"/job/(\d+)/", href)
                    job_id = m.group(1) if m else href
                    if job_id in seen_ids:
                        continue

                    full_url = href if href.startswith("http") else f"https://www.vanguardjobs.com{href}"
                    seen_ids.add(job_id)
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=full_url,
                            location="Hyderabad, India",
                        )
                    )
                del soup

        except Exception as e:
            logger.error(f"Playwright scraping error for Vanguard: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_obj:
                try:
                    await playwright_obj.stop()
                except Exception:
                    pass
            gc.collect()

        logger.info(f"Vanguard Playwright scraped {len(listings)} jobs.")
        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Vanguard curl scrape returned 0 jobs. Falling back to Playwright...")
        except Exception as e:
            logger.error(f"Vanguard curl scrape failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Vanguard Playwright scrape failed: {e}")
            return []
