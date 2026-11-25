import asyncio
import gc
import logging
import re
from typing import List, Set, Tuple, Optional
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class EYPortalAdapter(BaseJobAdapter):
    """
    Adapter for EY (Ernst & Young) Careers Portal.
    Target URL: https://careers.ey.com/search/?q=&q2=&alertId=&optionsFacetsDD_country=IN&title=Developer&location=#searchresults

    Filters:
      - Country: "IN" (optionsFacetsDD_country=IN)
      - Job Title: "Developer" (title=Developer)

    Network & Platform Architecture:
      - Platform: SAP SuccessFactors Recruitment Marketing (RMK) / Jobs2Web
      - Search results are returned as server-rendered HTML containing `table#searchresults`
        with rows marked as `tr.data-row`.
      - Pagination is controlled via the `startrow` query parameter (e.g. `startrow=0`, `startrow=25`, ...).
      - Primary Extraction: High-performance HTTP GET requests via curl_cffi AsyncSession with Chrome impersonation.
      - Secondary Fallback: Headless Playwright browser automation navigating pages.
    """

    TARGET_URL = (
        "https://careers.ey.com/search/"
        "?q=&q2=&alertId=&optionsFacetsDD_country=IN&title=Developer&location=#searchresults"
    )
    BASE_URL = "https://careers.ey.com"
    SEARCH_PATH = "/search/"
    PAGE_SIZE = 25
    MAX_PAGES = 20

    @property
    def portal_id(self) -> str:
        return "ey_careers"

    @property
    def portal_name(self) -> str:
        return "EY Careers Portal"

    def _build_search_url(self, startrow: int = 0) -> str:
        """Constructs the search URL for a given startrow offset."""
        if startrow == 0:
            return (
                f"{self.BASE_URL}{self.SEARCH_PATH}"
                "?q=&q2=&alertId=&optionsFacetsDD_country=IN&title=Developer&location=#searchresults"
            )
        return (
            f"{self.BASE_URL}{self.SEARCH_PATH}"
            f"?q=&q2=&alertId=&optionsFacetsDD_country=IN&title=Developer&location=&startrow={startrow}#searchresults"
        )

    def _parse_rows(self, html: str, seen_ids: Set[str]) -> Tuple[List[JobListing], Optional[int]]:
        """
        Parses `tr.data-row` elements from table#searchresults.
        Returns a tuple of (listings, total_count_if_found).
        """
        listings: List[JobListing] = []
        soup = BeautifulSoup(html, "html.parser")

        # Determine total results from pagination label if present (e.g. "Results 1 – 25 of 35")
        total_count: Optional[int] = None
        pagination_label = soup.select_one("span.paginationLabel")
        if pagination_label:
            m = re.search(r"of\s*(\d+)", pagination_label.get_text(), re.IGNORECASE)
            if m:
                try:
                    total_count = int(m.group(1))
                except ValueError:
                    pass

        rows = soup.select("table#searchresults tr.data-row")
        for row in rows:
            title_a = row.select_one("a.jobTitle-link, a[href*='/job/']")
            if not title_a:
                continue

            title = title_a.get_text(strip=True)
            href = (title_a.get("href") or "").strip()
            if not title or not href:
                continue

            # Extract numeric Job ID from URL slug (e.g. /ey/job/.../1460056233/)
            m_id = re.search(r"/job/[^/]+/(\d+)/?", href)
            job_id = m_id.group(1) if m_id else ""
            if not job_id:
                facility_el = row.select_one(".jobFacility, .colFacility")
                job_id = facility_el.get_text(strip=True) if facility_el else href

            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Location formatting
            loc_el = row.select_one("td.colLocation .jobLocation, .colLocation, .jobLocation")
            raw_loc = loc_el.get_text(strip=True) if loc_el else "India"

            # Strip "+X more…" if present
            loc = re.sub(r"\+\d+\s+more.*", "", raw_loc).strip()
            # Normalize country code to India
            loc = loc.replace(", IN,", ", India,").replace(", IN", ", India")
            if "india" not in loc.lower():
                loc = f"{loc}, India"

            full_link = f"{self.BASE_URL}{href}" if href.startswith("/") else href

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location=loc,
                )
            )

        return listings, total_count

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes EY Developer jobs via high-performance curl_cffi AsyncSession."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://careers.ey.com/",
        }

        all_listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome") as session:
            startrow = 0
            page_num = 1

            while page_num <= self.MAX_PAGES:
                url = self._build_search_url(startrow)
                logger.info(f"[{self.portal_id}] Fetching page {page_num} (startrow={startrow})...")

                try:
                    response = await session.get(url, headers=headers, timeout=30)
                except Exception as e:
                    logger.warning(f"[{self.portal_id}] Request failed for startrow={startrow}: {e}")
                    break

                if response.status_code != 200:
                    logger.warning(
                        f"[{self.portal_id}] HTTP {response.status_code} for URL: {url}"
                    )
                    break

                page_listings, total_count = self._parse_rows(response.text, seen_ids)
                if not page_listings:
                    logger.info(f"[{self.portal_id}] No more listings found at startrow={startrow}")
                    break

                all_listings.extend(page_listings)
                logger.info(
                    f"[{self.portal_id}] Page {page_num} yielded {len(page_listings)} listings (cumulative: {len(all_listings)})"
                )

                # Stop if all total items reached
                if total_count and len(all_listings) >= total_count:
                    logger.info(f"[{self.portal_id}] Reached total reported results: {total_count}")
                    break

                # If returned listings is less than page size, this is the last page
                if len(page_listings) < self.PAGE_SIZE:
                    break

                startrow += self.PAGE_SIZE
                page_num += 1
                await asyncio.sleep(0.3)

        return all_listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Secondary fallback: Scrapes EY Developer jobs via headless Playwright browser."""
        logger.info(f"[{self.portal_id}] Starting Playwright fallback...")
        all_listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                startrow = 0
                page_num = 1

                while page_num <= self.MAX_PAGES:
                    url = self._build_search_url(startrow)
                    logger.info(f"[{self.portal_id}] [Playwright] Navigating to page {page_num}: {url}")
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)

                    try:
                        await page.wait_for_selector("table#searchresults", timeout=15000)
                    except Exception:
                        logger.warning(f"[{self.portal_id}] [Playwright] Table not found on page {page_num}")
                        break

                    content = await page.content()
                    page_listings, total_count = self._parse_rows(content, seen_ids)

                    if not page_listings:
                        break

                    all_listings.extend(page_listings)
                    logger.info(
                        f"[{self.portal_id}] [Playwright] Page {page_num} yielded {len(page_listings)} listings (cumulative: {len(all_listings)})"
                    )

                    if total_count and len(all_listings) >= total_count:
                        break

                    if len(page_listings) < self.PAGE_SIZE:
                        break

                    startrow += self.PAGE_SIZE
                    page_num += 1
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"[{self.portal_id}] Playwright fallback encountered error: {e}")
            finally:
                try:
                    await page.close()
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

        return all_listings

    async def scrape(self) -> List[JobListing]:
        """Main scraping entrypoint: tries curl_cffi first, falls back to Playwright."""
        logger.info(f"[{self.portal_id}] Starting job scrape for {self.portal_name}...")
        listings: List[JobListing] = []

        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(
                    f"[{self.portal_id}] Successfully extracted {len(listings)} listings via curl_cffi"
                )
                return listings
            logger.warning(f"[{self.portal_id}] curl_cffi returned 0 listings, falling back to Playwright")
        except Exception as e:
            logger.warning(f"[{self.portal_id}] curl_cffi scrape failed: {e}. Falling back to Playwright")

        try:
            listings = await self._scrape_playwright()
            logger.info(
                f"[{self.portal_id}] Playwright fallback finished with {len(listings)} listings"
            )
        except Exception as e:
            logger.error(f"[{self.portal_id}] Playwright fallback failed: {e}")

        gc.collect()
        return listings
