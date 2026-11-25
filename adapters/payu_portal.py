import asyncio
import gc
import logging
import re
from typing import List, Set, Dict, Any, Optional
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class PayUPortalAdapter(BaseJobAdapter):
    """
    Adapter for PayU Careers Portal (SAP SuccessFactors RMK platform).
    Target URL: https://careers.payu.in/PayU/go/_/514880/?q=&q2=&alertId=&facility=&title=Software&location=&date=#searchresults
    
    Filters:
      - Title: "Software"
      
    Network & Platform Architecture:
      - Platform: SAP SuccessFactors Recruitment Marketing (RMK)
      - The search results are rendered in an HTML table `#searchresults` with `.data-row` elements.
      - Primary: High-performance HTTP GET via curl_cffi AsyncSession.
      - Secondary Fallback: Headless Playwright browser automation.
    """

    TARGET_URL = (
        "https://careers.payu.in/PayU/go/_/514880/"
        "?q=&q2=&alertId=&facility=&title=Software&location=&date=#searchresults"
    )
    BASE_URL = "https://careers.payu.in"
    BASE_SEARCH_PATH = "/PayU/go/_/514880"
    PARAMS = "?q=&q2=&alertId=&facility=&title=Software&location=&date=#searchresults"

    PAGE_SIZE = 25

    @property
    def portal_id(self) -> str:
        return "payu_careers"

    @property
    def portal_name(self) -> str:
        return "PayU Careers Portal"

    def _parse_rows(self, html: str, seen_ids: Set[str]) -> List[JobListing]:
        """Parses `tr.data-row` elements from the SuccessFactors searchresults table."""
        listings: List[JobListing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select("table#searchresults tr.data-row")
        for row in rows:
            title_a = row.select_one("a.jobTitle-link, a[href*='/job/']")
            if not title_a:
                continue

            title = title_a.get_text(strip=True)
            href = (title_a.get("href") or "").strip()
            if not title or not href:
                continue

            # Extract job ID from URL (e.g. /PayU/job/.../53362180/) or fallback to facility/req id
            m = re.search(r"/job/[^/]+/(\d+)/", href)
            job_id = m.group(1) if m else ""
            if not job_id:
                req_el = row.select_one(".jobFacility, .colFacility")
                job_id = req_el.get_text(strip=True) if req_el else href

            if not job_id or job_id in seen_ids:
                continue

            seen_ids.add(job_id)

            # Location extraction & formatting
            loc_el = row.select_one("td.colLocation .jobLocation, .colLocation")
            location = loc_el.get_text(strip=True) if loc_el else "India"
            if ", IN" in location:
                location = location.replace(", IN", ", India")
            elif "india" not in location.lower():
                location = f"{location}, India"

            full_link = f"{self.BASE_URL}{href}" if href.startswith("/") else href

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
        """Scrapes PayU job listings via high-performance curl_cffi AsyncSession."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        seen_ids: Set[str] = set()
        listings: List[JobListing] = []

        async with AsyncSession(impersonate="chrome124", headers=headers) as session:
            # 1. Fetch initial search page
            resp = await session.get(self.TARGET_URL, timeout=25)
            if resp.status_code != 200:
                logger.warning(f"PayU search page returned status {resp.status_code}")
                return []

            batch = self._parse_rows(resp.text, seen_ids)
            listings.extend(batch)

            # 2. Check if total results exceeds page size for pagination
            # Pattern: "Results 1 – 25 of 144"
            m = re.search(r"of\s*<b>?\s*(\d+)\s*</b>?", resp.text, re.I)
            total_count = int(m.group(1)) if m else len(batch)
            logger.info(f"PayU search reported {total_count} total jobs (page 1 got {len(batch)})")

            if total_count > self.PAGE_SIZE:
                offsets = list(range(self.PAGE_SIZE, total_count, self.PAGE_SIZE))
                sem = asyncio.Semaphore(4)

                async def fetch_offset(off: int) -> List[JobListing]:
                    async with sem:
                        url = f"{self.BASE_URL}{self.BASE_SEARCH_PATH}/{off}/{self.PARAMS}"
                        try:
                            r = await session.get(url, timeout=25)
                            if r.status_code == 200:
                                return self._parse_rows(r.text, seen_ids)
                        except Exception as e:
                            logger.error(f"Error fetching PayU offset {off}: {e}")
                    return []

                results = await asyncio.gather(*[fetch_offset(off) for off in offsets])
                for b in results:
                    listings.extend(b)

        logger.info(f"PayU curl_cffi successfully scraped {len(listings)} listings")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Headless Playwright fallback for PayU Careers portal."""
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        browser = None
        context = None
        page = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--single-process",
                    ],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                # Block heavy assets to minimize memory footprint
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ["image", "media", "font", "stylesheet"]
                    else route.continue_(),
                )

                logger.info(f"Navigating to PayU Careers URL: {self.TARGET_URL}")
                await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector("table#searchresults tr.data-row", timeout=10000)

                content = await page.content()
                listings = self._parse_rows(content, seen_ids)

        except Exception as e:
            logger.error(f"Playwright scraping failed for PayU Careers: {e}")
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            gc.collect()

        return listings

    async def scrape(self) -> List[JobListing]:
        """Main entry point: attempts high-speed curl_cffi first, falls back to Playwright."""
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"PayU portal scraped {len(listings)} jobs via curl_cffi")
                return listings
            logger.warning("PayU curl_cffi returned 0 jobs, falling back to Playwright")
        except Exception as e:
            logger.warning(f"PayU curl_cffi failed ({e}), falling back to Playwright")

        listings = await self._scrape_playwright()
        logger.info(f"PayU portal scraped {len(listings)} jobs via Playwright")
        return listings
