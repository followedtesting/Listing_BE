import asyncio
import gc
import json
import logging
import re
from typing import List, Set, Dict, Any, Optional
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class HDFCBankPortalAdapter(BaseJobAdapter):
    """
    Adapter for HDFC Bank Careers Portal (hosted on RippleHire).
    Target URL: https://hdfcbank.ripplehire.com/candidate/?token=pvB5iAMcmu4ydUh2IW2O&source=CAREERSITE#list/search=Developer

    Search Criteria:
      - Keyword search: "Developer" (search=Developer)

    Network & Platform Architecture:
      - Platform: RippleHire ATS Candidate Portal
      - Primary Endpoint: POST `https://hdfcbank.ripplehire.com/candidate/candidatejobsearch`
        with payload:
          careerSiteUrlParams={"page": 0, "search": "Developer", "token": "...", "source": "CAREERSITE", "pagesize": 50}
          lang=en
        Accept: application/json
      - Job URLs: `https://hdfcbank.ripplehire.com/candidate/?token={token}&source={source}#detail/job/{job_seq}`
      - Secondary Fallback: Headless Playwright browser automation navigating to `#list/search=Developer`
        and extracting job cards with selector `a[href*='#detail/job/']`.
    """

    TARGET_URL = (
        "https://hdfcbank.ripplehire.com/candidate/"
        "?token=pvB5iAMcmu4ydUh2IW2O&source=CAREERSITE#list/search=Developer"
    )
    BASE_URL = "https://hdfcbank.ripplehire.com"
    API_URL = "https://hdfcbank.ripplehire.com/candidate/candidatejobsearch"

    TOKEN = "pvB5iAMcmu4ydUh2IW2O"
    SOURCE = "CAREERSITE"
    SEARCH_KEYWORD = "Developer"
    PAGE_SIZE = 50
    MAX_PAGES = 10

    @property
    def portal_id(self) -> str:
        return "hdfc_bank_careers"

    @property
    def portal_name(self) -> str:
        return "HDFC Bank Careers Portal"

    def _normalize_location(self, raw_loc: str) -> str:
        """Normalizes location strings to include India if not already present."""
        loc = raw_loc.strip()
        if not loc:
            return "India"
        if "india" not in loc.lower():
            return f"{loc}, India"
        return loc

    def _parse_job_items(self, job_list: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        """Parses job objects from candidatejobsearch JSON response."""
        listings: List[JobListing] = []

        for j in job_list:
            if not isinstance(j, dict):
                continue

            job_seq = str(j.get("jobSeq") or j.get("jobId") or j.get("jobCode") or "").strip()
            title = (j.get("jobTitle") or "").strip()

            if not job_seq or not title:
                continue

            if job_seq in seen_ids:
                continue
            seen_ids.add(job_seq)

            raw_loc = (j.get("locations") or j.get("jobLocation") or "India").strip()
            location = self._normalize_location(raw_loc)

            link = (
                f"{self.BASE_URL}/candidate/?token={self.TOKEN}&source={self.SOURCE}#detail/job/{job_seq}"
            )

            listings.append(
                JobListing(
                    jobid=job_seq,
                    role_name=title,
                    job_listing_link=link,
                    location=location,
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes HDFC Bank developer jobs via high-performance curl_cffi AsyncSession."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": self.TARGET_URL,
            "Origin": self.BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }

        all_listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome") as session:
            page_idx = 0

            while page_idx < self.MAX_PAGES:
                params = {
                    "page": page_idx,
                    "search": self.SEARCH_KEYWORD,
                    "token": self.TOKEN,
                    "source": self.SOURCE,
                    "pagesize": self.PAGE_SIZE,
                }
                payload = {
                    "careerSiteUrlParams": json.dumps(params),
                    "lang": "en",
                }

                logger.info(
                    f"[{self.portal_id}] Requesting candidatejobsearch page {page_idx} (pagesize={self.PAGE_SIZE})..."
                )
                try:
                    response = await session.post(
                        self.API_URL, data=payload, headers=headers, timeout=30
                    )
                except Exception as e:
                    logger.warning(f"[{self.portal_id}] HTTP POST failed on page {page_idx}: {e}")
                    break

                if response.status_code != 200:
                    logger.warning(
                        f"[{self.portal_id}] candidatejobsearch returned status {response.status_code}"
                    )
                    break

                try:
                    data = response.json()
                except Exception as e:
                    logger.warning(f"[{self.portal_id}] Failed to parse JSON response: {e}")
                    break

                job_list = data.get("jobVoList", [])
                total_count = data.get("totalJobCount", 0)

                if not job_list:
                    logger.info(f"[{self.portal_id}] No jobs returned on page {page_idx}")
                    break

                page_listings = self._parse_job_items(job_list, seen_ids)
                all_listings.extend(page_listings)

                logger.info(
                    f"[{self.portal_id}] Page {page_idx} yielded {len(page_listings)} listings "
                    f"(cumulative: {len(all_listings)}, total reported: {total_count})"
                )

                if total_count and len(all_listings) >= total_count:
                    break

                if len(job_list) < self.PAGE_SIZE:
                    break

                page_idx += 1
                await asyncio.sleep(0.3)

        return all_listings

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
                await page.goto(self.TARGET_URL, wait_until="networkidle", timeout=45000)
                await page.wait_for_timeout(3000)

                try:
                    await page.wait_for_selector("a[href*='#detail/job/']", timeout=15000)
                except Exception:
                    logger.warning(f"[{self.portal_id}] Job detail links not found in DOM")

                cards = await page.locator("a[href*='#detail/job/']").all()
                for card in cards:
                    title = (await card.inner_text()).strip()
                    href = (await card.get_attribute("href") or "").strip()
                    if not title or not href:
                        continue

                    m = re.search(r"/job/(\d+)", href)
                    job_id = m.group(1) if m else href

                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    # Extract location from card parent context
                    location = "India"
                    try:
                        parent_text = await card.locator("xpath=../..").inner_text()
                        for line in parent_text.splitlines():
                            line_s = line.strip()
                            if any(
                                city in line_s.lower()
                                for city in ["bangalore", "mumbai", "pune", "hyderabad", "chennai", "delhi", "noida", "gurgaon"]
                            ):
                                location = self._normalize_location(line_s.strip("| "))
                                break
                    except Exception:
                        pass

                    full_link = (
                        f"{self.BASE_URL}/candidate/?token={self.TOKEN}&source={self.SOURCE}#detail/job/{job_id}"
                    )

                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=full_link,
                            location=location,
                        )
                    )

                logger.info(f"[{self.portal_id}] Playwright extracted {len(listings)} listings from DOM")

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
