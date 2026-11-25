import asyncio
import gc
import json
import logging
import re
from typing import List, Set, Dict, Any, Optional
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class PwCIndiaPortalAdapter(BaseJobAdapter):
    """
    Adapter for PwC India Experienced Careers Portal.
    Target URL: https://www.pwc.in/careers/experienced-jobs.html

    Search / Filter Criteria:
      - Searches for "Developer" in the job table search bar.
      - Filters and extracts only those listings matching "Developer".

    Platform & Data Architecture:
      - Platform: PwC Careers / Adobe Experience Manager + Workday Integration
      - The complete catalog of experienced job listings is embedded directly in the page HTML
        within an inline script block as `var jsondata = [...]`.
      - The frontend table (`#wdresults`) initializes a Bootstrap Table from this JSON dataset.
      - Primary Extraction: High-performance HTTP GET using curl_cffi AsyncSession with Chrome
        impersonation, parsing the embedded `var jsondata` directly and filtering for "developer".
      - Secondary Fallback: Headless Playwright browser automation evaluating `window.jsondata`
        or searching the Bootstrap Table with `resetSearch`.
    """

    TARGET_URL = "https://www.pwc.in/careers/experienced-jobs.html"
    BASE_URL = "https://www.pwc.in"
    SEARCH_KEYWORD = "developer"

    @property
    def portal_id(self) -> str:
        return "pwc_india_careers"

    @property
    def portal_name(self) -> str:
        return "PwC India Careers Portal"

    def _parse_job_data(self, raw_items: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        """Filters items for the search keyword ('developer') and converts to JobListing objects."""
        listings: List[JobListing] = []

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            title = (item.get("title") or "").strip()
            job_req_id = (item.get("jobreqid") or "").strip()

            if not title:
                continue

            # Filter for "Developer" in the title (matches table search behaviour)
            if self.SEARCH_KEYWORD not in title.lower():
                continue

            job_id = job_req_id or title
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            apply_link = (item.get("apply") or "").strip()
            if not apply_link:
                apply_link = (
                    f"{self.BASE_URL}/careers/experienced-jobs/description.html?wdjobreqid={job_id}"
                )

            location_val = (item.get("location") or "").strip()
            if location_val:
                if "india" not in location_val.lower():
                    location = f"{location_val}, India"
                else:
                    location = location_val
            else:
                location = "India"

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=apply_link,
                    location=location,
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes PwC India experienced jobs via high-performance curl_cffi AsyncSession."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.pwc.in/careers.html",
        }

        async with AsyncSession(impersonate="chrome") as session:
            response = await session.get(self.TARGET_URL, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.warning(
                    f"[{self.portal_id}] HTTP GET {self.TARGET_URL} returned status {response.status_code}"
                )
                return []

            html = response.text
            start_marker = "var jsondata = "
            start_idx = html.find(start_marker)
            if start_idx == -1:
                logger.warning(f"[{self.portal_id}] 'var jsondata' marker not found in HTML response")
                return []

            sub_str = html[start_idx + len(start_marker):]
            end_idx = sub_str.find("var dbdata")
            if end_idx != -1:
                sub_str = sub_str[:end_idx]

            last_bracket = sub_str.rfind("]")
            if last_bracket == -1:
                logger.warning(f"[{self.portal_id}] Closing ']' for jsondata array not found")
                return []

            raw_json = sub_str[: last_bracket + 1].strip()
            try:
                data = json.loads(raw_json)
            except Exception as e:
                logger.warning(f"[{self.portal_id}] Failed to parse jsondata: {e}")
                return []

            seen_ids: Set[str] = set()
            return self._parse_job_data(data, seen_ids)

    async def _scrape_playwright(self) -> List[JobListing]:
        """Secondary fallback: Scrapes via headless Playwright browser."""
        logger.info(f"[{self.portal_id}] Starting Playwright fallback...")
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
                await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=45000)

                # Attempt 1: Extract from window.jsondata
                raw_data = await page.evaluate(
                    """() => {
                        if (window.jsondata && Array.isArray(window.jsondata)) {
                            return window.jsondata;
                        }
                        return null;
                    }"""
                )

                if raw_data and isinstance(raw_data, list):
                    listings = self._parse_job_data(raw_data, seen_ids)
                    if listings:
                        logger.info(
                            f"[{self.portal_id}] Extracted {len(listings)} listings via Playwright window.jsondata"
                        )
                        return listings

                # Attempt 2: Wait for table and use bootstrapTable search
                await page.wait_for_selector("#wdresults", timeout=15000)
                table_data = await page.evaluate(
                    """() => {
                        if (window.$ && $("#wdresults").data("bootstrap.table")) {
                            $("#wdresults").bootstrapTable("resetSearch", "Developer");
                            return $("#wdresults").bootstrapTable("getData");
                        }
                        return null;
                    }"""
                )

                if table_data and isinstance(table_data, list):
                    listings = self._parse_job_data(table_data, seen_ids)
                    if listings:
                        logger.info(
                            f"[{self.portal_id}] Extracted {len(listings)} listings via Bootstrap Table resetSearch"
                        )
                        return listings

            except Exception as e:
                logger.error(f"[{self.portal_id}] Playwright fallback encountered error: {e}")
            finally:
                try:
                    await page.close()
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

        return listings

    async def scrape(self) -> List[JobListing]:
        """Main scraping entrypoint: tries curl_cffi first, falls back to Playwright."""
        logger.info(f"[{self.portal_id}] Starting job scrape for {self.portal_name}...")
        listings: List[JobListing] = []

        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(
                    f"[{self.portal_id}] Successfully extracted {len(listings)} Developer listings via curl_cffi"
                )
                return listings
            logger.warning(f"[{self.portal_id}] curl_cffi returned 0 listings, falling back to Playwright")
        except Exception as e:
            logger.warning(f"[{self.portal_id}] curl_cffi scrape failed: {e}. Falling back to Playwright")

        try:
            listings = await self._scrape_playwright()
            logger.info(
                f"[{self.portal_id}] Playwright fallback finished with {len(listings)} Developer listings"
            )
        except Exception as e:
            logger.error(f"[{self.portal_id}] Playwright fallback failed: {e}")

        gc.collect()
        return listings
