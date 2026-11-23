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


class MacquariePortalAdapter(BaseJobAdapter):
    """
    Adapter for Macquarie Group Careers Portal.
    Target URL: https://recruitment.macquarie.com/en_US/careers/SearchJobs/?1270=%5B347511%5D&1270_format=3248&listFilterMode=1&jobRecordsPerPage=9&
    
    Filters:
      - Category: "Technology - Engineering" (1270=[347511], 1270_format=3248)
      
    Network & Platform Architecture:
      - Server-rendered HTML with offset-based pagination (jobRecordsPerPage=9, jobOffset=0, 9, 18, ...).
      - Primary: High-performance parallelized HTTP GET requests via curl_cffi AsyncSession.
      - Secondary Fallback: Headless Playwright browser automation.
    """

    TARGET_URL = (
        "https://recruitment.macquarie.com/en_US/careers/SearchJobs/"
        "?1270=%5B347511%5D&1270_format=3248&listFilterMode=1&jobRecordsPerPage=9&"
    )
    BASE_SEARCH_URL = "https://recruitment.macquarie.com/en_US/careers/SearchJobs/"
    PARAMS = "?1270=%5B347511%5D&1270_format=3248&listFilterMode=1&jobRecordsPerPage=9"
    BASE_URL = "https://recruitment.macquarie.com"

    RECORDS_PER_PAGE = 9

    @property
    def portal_id(self) -> str:
        return "macquarie_careers"

    @property
    def portal_name(self) -> str:
        return "Macquarie Careers Portal"

    def _parse_cards(self, html: str, seen_ids: Set[str]) -> List[JobListing]:
        """Parses `article.article--result` elements from the Macquarie HTML page."""
        listings: List[JobListing] = []
        soup = BeautifulSoup(html, "html.parser")

        cards = soup.select("article.article--result")
        for c in cards:
            title_el = c.select_one(".article__header a, h3.title a")
            title = title_el.get_text(strip=True) if title_el else ""
            href = (title_el.get("href") or "").strip() if title_el else ""

            if not title or not href:
                continue

            # Extract jobId
            m = re.search(r"jobId=(\d+)", href)
            job_id = m.group(1) if m else ""
            if not job_id:
                id_p = c.find("p", class_="icon", string="ID")
                if id_p and id_p.find_next_sibling("p"):
                    job_id = id_p.find_next_sibling("p").get_text(strip=True)

            if not job_id or job_id in seen_ids:
                continue

            seen_ids.add(job_id)

            # Extract location
            loc_img = c.find("img", alt=re.compile(r"location", re.I))
            if loc_img and loc_img.find_next_sibling("p"):
                location = loc_img.find_next_sibling("p").get_text(strip=True)
            else:
                location = "Macquarie Office"

            full_link = href if href.startswith("http") else f"{self.BASE_URL}{href}"

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
        """Scrapes Macquarie job listings via high-performance curl_cffi AsyncSession with concurrent offset pagination."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        seen_ids: Set[str] = set()
        listings: List[JobListing] = []

        async with AsyncSession(impersonate="chrome124", headers=headers) as session:
            # 1. Fetch initial page (offset=0)
            page1_url = f"{self.BASE_SEARCH_URL}{self.PARAMS}&jobOffset=0"
            r1 = await session.get(page1_url, timeout=25)
            if r1.status_code != 200:
                logger.warning(f"Macquarie search page returned status {r1.status_code}")
                return []

            p1_listings = self._parse_cards(r1.text, seen_ids)
            listings.extend(p1_listings)

            # 2. Extract total results count (e.g. "of 75 results")
            m = re.search(r"of\s+(\d+)\s+results", r1.text, re.I)
            total_count = int(m.group(1)) if m else len(p1_listings)
            logger.info(f"Macquarie total search results reported: {total_count}")

            # 3. Concurrently fetch remaining offsets with bounded semaphore
            offsets = list(range(self.RECORDS_PER_PAGE, total_count, self.RECORDS_PER_PAGE))
            if offsets:
                sem = asyncio.Semaphore(4)

                async def fetch_offset(off: int) -> List[JobListing]:
                    async with sem:
                        url = f"{self.BASE_SEARCH_URL}{self.PARAMS}&jobOffset={off}"
                        try:
                            resp = await session.get(url, timeout=25)
                            if resp.status_code == 200:
                                return self._parse_cards(resp.text, seen_ids)
                        except Exception as e:
                            logger.error(f"Error fetching Macquarie offset {off}: {e}")
                    return []

                results = await asyncio.gather(*[fetch_offset(off) for off in offsets])
                for batch in results:
                    listings.extend(batch)

        logger.info(f"Macquarie curl_cffi successfully scraped {len(listings)} listings")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Headless Playwright fallback for Macquarie Careers portal."""
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

                logger.info(f"Navigating to Macquarie Careers URL: {self.TARGET_URL}")
                offset = 0
                max_pages = 15

                for p_idx in range(1, max_pages + 1):
                    current_url = f"{self.BASE_SEARCH_URL}{self.PARAMS}&jobOffset={offset}"
                    await page.goto(current_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_selector("article.article--result", timeout=10000)

                    content = await page.content()
                    batch = self._parse_cards(content, seen_ids)
                    listings.extend(batch)

                    # Check if there is another page
                    has_next = await page.query_selector("a.paginationNextLink, .paginationNextLink a")
                    if not has_next or len(batch) < self.RECORDS_PER_PAGE:
                        break

                    offset += self.RECORDS_PER_PAGE

        except Exception as e:
            logger.error(f"Playwright scraping failed for Macquarie Careers: {e}")
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
                logger.info(f"Macquarie portal scraped {len(listings)} jobs via curl_cffi")
                return listings
            logger.warning("Macquarie curl_cffi returned 0 jobs, falling back to Playwright")
        except Exception as e:
            logger.warning(f"Macquarie curl_cffi failed ({e}), falling back to Playwright")

        listings = await self._scrape_playwright()
        logger.info(f"Macquarie portal scraped {len(listings)} jobs via Playwright")
        return listings
