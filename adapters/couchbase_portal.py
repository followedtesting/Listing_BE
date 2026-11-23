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


class CouchbasePortalAdapter(BaseJobAdapter):
    """
    Adapter for Couchbase Careers Portal.
    Target URL: https://www.couchbase.com/careers/#job-openings
    
    Filters:
      - Location: "Bangalore, India"
      - Department: "Engineering"
      
    Network & Platform Architecture:
      - Couchbase's frontend `#job-openings` widget consumes the Greenhouse API at:
        https://boards-api.greenhouse.io/v1/boards/couchbaseinc/jobs
      - The frontend dropdowns group teams by the metadata field 'Job Site Team' (bucketId: 4488138006),
        where Department "Engineering" corresponds to `metadata.value == 'Engineering'` (mapped to R&D Core).
      - Primary: Direct high-speed GET request to Greenhouse REST API via curl_cffi.
      - Secondary Fallback: Headless Playwright browser automation on Couchbase's Greenhouse job board.
    """

    TARGET_URL = "https://www.couchbase.com/careers/#job-openings"
    BASE_URL = "https://www.couchbase.com"
    GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards/couchbaseinc/jobs?content=true"
    GREENHOUSE_BOARD_URL = "https://job-boards.greenhouse.io/couchbaseinc"

    BUCKET_ID = 4488138006  # Metadata field ID for 'Job Site Team'
    LOCATION_KEYWORDS = ["bangalore", "bengaluru"]
    DEPARTMENT_KEYWORDS = ["engineering", "r&d", "core"]

    @property
    def portal_id(self) -> str:
        return "couchbase_careers"

    @property
    def portal_name(self) -> str:
        return "Couchbase Careers Portal"

    def _matches_filters(self, job: Dict[str, Any]) -> bool:
        """Evaluates whether a Greenhouse job dictionary matches Bangalore + Engineering criteria."""
        # 1. Location check
        loc = (job.get("location", {}).get("name") or "").lower()
        if not any(k in loc for k in self.LOCATION_KEYWORDS):
            return False

        # 2. Department check
        # A. Primary: Check custom metadata field 'Job Site Team' (bucketId: 4488138006)
        meta_list = job.get("metadata") or []
        team_meta = next(
            (m for m in meta_list if m.get("id") == self.BUCKET_ID or m.get("name") == "Job Site Team"),
            None,
        )
        if team_meta and team_meta.get("value"):
            val = str(team_meta.get("value")).lower()
            if "engineering" in val:
                return True

        # B. Secondary: Check Greenhouse departments array
        depts = [str(d.get("name") or "").lower() for d in job.get("departments") or []]
        if any(any(k in d for k in self.DEPARTMENT_KEYWORDS) for d in depts):
            return True

        # C. Tertiary fallback: Check title
        title = (job.get("title") or "").lower()
        if "engineer" in title:
            return True

        return False

    def _parse_job_items(self, jobs: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        """Parses Greenhouse job objects into JobListing instances."""
        listings: List[JobListing] = []

        for j in jobs:
            if not isinstance(j, dict):
                continue

            job_id = str(j.get("id") or "").strip()
            title = (j.get("title") or "").strip()

            if not job_id or not title:
                continue

            if job_id in seen_ids:
                continue

            if not self._matches_filters(j):
                continue

            seen_ids.add(job_id)

            location = (j.get("location", {}).get("name") or "Bangalore, India").strip()
            link = (j.get("absolute_url") or "").strip()
            if not link:
                link = f"https://job-boards.greenhouse.io/couchbaseinc/jobs/{job_id}"

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
        """Scrapes Couchbase jobs via high-performance Greenhouse REST API using curl_cffi."""
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(self.GREENHOUSE_API_URL, headers=headers, timeout=25)
            if resp.status_code != 200:
                logger.warning(f"Greenhouse API for Couchbase returned HTTP {resp.status_code}")
                return []

            try:
                data = resp.json()
            except Exception as e:
                logger.error(f"Failed to parse Couchbase Greenhouse API response: {e}")
                return []

            jobs = data.get("jobs", [])
            listings = self._parse_job_items(jobs, seen_ids)
            logger.info(f"Couchbase Greenhouse API filtered to {len(listings)} listings")
            return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Headless Playwright browser fallback for Couchbase Greenhouse job board."""
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

                logger.info(f"Navigating to Couchbase Greenhouse board: {self.GREENHOUSE_BOARD_URL}")
                await page.goto(self.GREENHOUSE_BOARD_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector("a[href*='/couchbaseinc/jobs/']", timeout=10000)

                # Extract listings from DOM
                raw_items = await page.evaluate("""() => {
                    const results = [];
                    for (const a of document.querySelectorAll("a[href*='/couchbaseinc/jobs/']")) {
                        const titleEl = a.querySelector('.body--medium, p:first-child');
                        const locEl = a.querySelector('.body--metadata, p:last-child');
                        const title = titleEl ? titleEl.innerText.trim() : a.innerText.trim();
                        const loc = locEl ? locEl.innerText.trim() : '';
                        const section = a.closest('section, div[id*="dept"], div');
                        const heading = section ? (section.querySelector('h2, h3, h4')?.innerText.trim() || '') : '';
                        results.push({
                            title,
                            loc,
                            heading,
                            href: a.href
                        });
                    }
                    return results;
                }""")

                for item in raw_items:
                    href = item.get("href", "")
                    title = item.get("title", "")
                    loc = item.get("loc", "")
                    heading = item.get("heading", "").lower()

                    # Clean "New" suffix if attached by badge
                    clean_title = re.sub(r"New$", "", title).strip()

                    # Check location and department filters
                    if not any(k in loc.lower() for k in self.LOCATION_KEYWORDS):
                        continue

                    is_eng = (
                        any(k in heading for k in self.DEPARTMENT_KEYWORDS)
                        or "engineer" in clean_title.lower()
                    )
                    if not is_eng:
                        continue

                    # Extract job ID
                    m = re.search(r"/jobs/(\d+)", href)
                    job_id = m.group(1) if m else href.split("/")[-1]

                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    listings.append(
                        JobListing(
                            jobid=str(job_id),
                            role_name=clean_title,
                            job_listing_link=href,
                            location=loc or "Bangalore, India",
                        )
                    )

        except Exception as e:
            logger.error(f"Playwright scraping failed for Couchbase: {e}")
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
                logger.info(f"Couchbase portal scraped {len(listings)} jobs via curl_cffi")
                return listings
            logger.warning("Couchbase curl_cffi returned 0 jobs, falling back to Playwright")
        except Exception as e:
            logger.warning(f"Couchbase curl_cffi failed ({e}), falling back to Playwright")

        listings = await self._scrape_playwright()
        logger.info(f"Couchbase portal scraped {len(listings)} jobs via Playwright")
        return listings
