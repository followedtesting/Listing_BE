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


class NICEPortalAdapter(BaseJobAdapter):
    """
    Adapter for NICE Careers Portal.
    Target URL: https://www.nice.com/careers/apply?category=PRODUCT+MANAGEMENT&location=India+-+Mumbai%3BIndia+-+Pune

    Filters:
      - Category: "PRODUCT MANAGEMENT"
      - Location: "India - Mumbai" or "India - Pune"

    Network & Platform Architecture:
      - Frontend / Hosting: Next.js App Router on www.nice.com.
      - ATS / Backend: Greenhouse EU Board (`boards.eu.greenhouse.io/nice`).
      - On www.nice.com/careers/apply, the Next.js server-side renderer directly outputs
        matching jobs in `<div class="job-resluts-inner">` as `<a class="result-item">` elements.
      - Primary Extraction: High-performance HTTP GET to www.nice.com with Chrome impersonation.
      - Direct API Fallback: Greenhouse Board API (`https://api.greenhouse.io/v1/boards/nice/jobs?content=true`)
        filtering for Category = "PRODUCT MANAGEMENT" and Location in {"India - Mumbai", "India - Pune"}.
      - Browser Fallback: Headless Playwright browser automation on the careers apply page.
    """

    TARGET_URL = (
        "https://www.nice.com/careers/apply"
        "?category=PRODUCT+MANAGEMENT&location=India+-+Mumbai%3BIndia+-+Pune"
    )
    BASE_URL = "https://www.nice.com"
    GREENHOUSE_API_URL = "https://api.greenhouse.io/v1/boards/nice/jobs?content=true"

    TARGET_CATEGORY = "PRODUCT MANAGEMENT"
    TARGET_LOCATIONS = {"india - mumbai", "india - pune", "mumbai", "pune"}

    @property
    def portal_id(self) -> str:
        return "nice_careers"

    @property
    def portal_name(self) -> str:
        return "NICE Careers Portal"

    def _normalize_location(self, raw_loc: str) -> str:
        """Normalizes 'India - Mumbai' or 'India - Pune' to 'Mumbai, India' / 'Pune, India'."""
        loc = raw_loc.strip()
        if loc.lower().startswith("india - "):
            city = loc[8:].strip()
            return f"{city}, India"
        if "india" not in loc.lower():
            return f"{loc}, India"
        return loc

    def _parse_html_items(self, html: str, seen_ids: Set[str]) -> List[JobListing]:
        """Parses `a.result-item` from www.nice.com/careers/apply HTML."""
        listings: List[JobListing] = []
        soup = BeautifulSoup(html, "html.parser")

        items = soup.select(".job-resluts-inner a.result-item, a.result-item, [class*='job-resluts'] a")
        for item in items:
            h4 = item.find("h4")
            if not h4:
                continue

            title = h4.get_text(strip=True)
            href = (item.get("href") or "").strip()
            if not title or not href:
                continue

            # Extract Greenhouse Job ID
            m = re.search(r"/jobs/(\d+)", href) or re.search(r"gh_jid=(\d+)", href)
            job_id = m.group(1) if m else href

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            p = item.find("p")
            raw_loc = p.get_text(strip=True) if p else "India"
            location = self._normalize_location(raw_loc)

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

    def _parse_greenhouse_json(self, data: Dict[str, Any], seen_ids: Set[str]) -> List[JobListing]:
        """Parses jobs from the direct Greenhouse Board API."""
        listings: List[JobListing] = []
        jobs = data.get("jobs", [])

        for job in jobs:
            job_id = str(job.get("id") or "").strip()
            title = (job.get("title") or "").strip()
            link = (job.get("absolute_url") or "").strip()

            if not job_id or not title or not link or job_id in seen_ids:
                continue

            # Check Category metadata
            category = ""
            for meta in job.get("metadata", []):
                if meta.get("name") == "Category":
                    val = meta.get("value")
                    category = str(val).strip() if val else ""
                    break

            if category.upper() != self.TARGET_CATEGORY:
                continue

            # Check Location
            loc_obj = job.get("location") or {}
            loc_name = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)
            offices = [o.get("name", "") for o in job.get("offices", []) if isinstance(o, dict)]

            all_loc_strings = [loc_name] + offices
            is_matching_loc = any(
                any(target in s.lower() for target in self.TARGET_LOCATIONS)
                for s in all_loc_strings
            )

            if not is_matching_loc:
                continue

            seen_ids.add(job_id)
            location = self._normalize_location(loc_name or offices[0] if offices else "India")

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=link,
                    location=location,
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes NICE jobs via high-performance curl_cffi AsyncSession."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nice.com/careers",
        }

        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome") as session:
            # 1. Primary: Try fetching the filtered page directly from nice.com
            try:
                response = await session.get(self.TARGET_URL, headers=headers, timeout=30)
                if response.status_code == 200:
                    listings = self._parse_html_items(response.text, seen_ids)
                    if listings:
                        logger.info(
                            f"[{self.portal_id}] Extracted {len(listings)} listings from nice.com careers HTML"
                        )
                        return listings
                else:
                    logger.warning(
                        f"[{self.portal_id}] nice.com returned status {response.status_code}"
                    )
            except Exception as e:
                logger.warning(f"[{self.portal_id}] Error fetching nice.com HTML: {e}")

            # 2. Secondary API: Fetch from Greenhouse Board API directly
            logger.info(f"[{self.portal_id}] Querying Greenhouse Board API as direct fallback...")
            try:
                gh_resp = await session.get(self.GREENHOUSE_API_URL, headers=headers, timeout=30)
                if gh_resp.status_code == 200:
                    gh_data = gh_resp.json()
                    listings = self._parse_greenhouse_json(gh_data, seen_ids)
                    if listings:
                        logger.info(
                            f"[{self.portal_id}] Extracted {len(listings)} listings from Greenhouse Board API"
                        )
                        return listings
                else:
                    logger.warning(
                        f"[{self.portal_id}] Greenhouse API returned status {gh_resp.status_code}"
                    )
            except Exception as e:
                logger.warning(f"[{self.portal_id}] Error querying Greenhouse API: {e}")

        return []

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

                # Wait for result-item elements or timeout gracefully
                try:
                    await page.wait_for_selector(
                        ".job-resluts-inner a.result-item, a.result-item", timeout=15000
                    )
                except Exception:
                    pass

                content = await page.content()
                listings = self._parse_html_items(content, seen_ids)
                logger.info(
                    f"[{self.portal_id}] Playwright extracted {len(listings)} listings from rendered page"
                )

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
        """Main scraping entrypoint: tries curl_cffi (HTML + Greenhouse API), falls back to Playwright."""
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
