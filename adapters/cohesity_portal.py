import asyncio
import gc
import logging
from typing import List, Set, Dict, Any, Optional
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class CohesityPortalAdapter(BaseJobAdapter):
    """
    Adapter for Cohesity Careers Portal.
    Target URL: https://www.cohesity.com/careers/open-positions/
    Filters:
      - Department: "Engineering"
      - Office Location: "India"
    Network Call:
      - Primary: GET https://www.cohesity.com/bin/cohesity/open-positions
      - Secondary Fallback: POST https://cohesity.wd5.myworkdayjobs.com/wday/cxs/cohesity/Cohesity_Careers/jobs
    """

    TARGET_URL = "https://www.cohesity.com/careers/open-positions/"
    API_URL = "https://www.cohesity.com/bin/cohesity/open-positions"
    WORKDAY_API_URL = "https://cohesity.wd5.myworkdayjobs.com/wday/cxs/cohesity/Cohesity_Careers/jobs"

    TARGET_DEPARTMENT = "Engineering"
    TARGET_COUNTRY = "India"

    @property
    def portal_id(self) -> str:
        return "cohesity_careers"

    @property
    def portal_name(self) -> str:
        return "Cohesity Careers Portal"

    def _parse_job_data(self, data: Dict[str, Any], seen_ids: Set[str]) -> List[JobListing]:
        """Parses the Cohesity open-positions JSON payload filtering by Department and Location."""
        listings: List[JobListing] = []
        job_data = data.get("job_data", {})

        target_dept_lower = self.TARGET_DEPARTMENT.strip().lower()
        target_country_lower = self.TARGET_COUNTRY.strip().lower()

        for dept_name, jobs in job_data.items():
            if not isinstance(jobs, list):
                continue

            # Filter by Department = "Engineering"
            if dept_name.strip().lower() != target_dept_lower:
                continue

            for j in jobs:
                if not isinstance(j, dict):
                    continue

                country = (j.get("country") or "").strip()
                primary_loc = (j.get("primaryLocation") or "").strip()
                regional = (j.get("jobSite_Regional") or "").strip()
                regional_list = j.get("jobSiteRegionalList") or []

                # Filter by Office Location = "India"
                is_india = (
                    country.lower() == target_country_lower
                    or target_country_lower in primary_loc.lower()
                    or target_country_lower in regional.lower()
                    or any(target_country_lower in str(loc).lower() for loc in regional_list)
                )

                if not is_india:
                    continue

                # Prefer requisition ID (e.g. R05092), fallback to internal JobID, then link slug
                job_id = (j.get("req_id") or j.get("JobID") or "").strip()
                title = (j.get("title") or "").strip()
                link = (j.get("jobUrl") or "").strip()

                if not job_id and link:
                    job_id = link.rstrip("/").split("/")[-1].replace("/apply", "")

                if not job_id or not title:
                    continue

                if job_id in seen_ids:
                    continue

                # Format location display
                loc = primary_loc or country or "India"
                if "india" not in loc.lower():
                    location = f"{loc}, India"
                else:
                    location = loc

                seen_ids.add(job_id)
                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=link or self.TARGET_URL,
                        location=location,
                    )
                )

        return listings

    def _parse_workday_backup(self, data: Dict[str, Any], seen_ids: Set[str]) -> List[JobListing]:
        """Backup parser for direct Workday CXS response in case Cohesity endpoint undergoes maintenance."""
        listings: List[JobListing] = []
        postings = data.get("jobPostings", [])

        target_country_lower = self.TARGET_COUNTRY.strip().lower()

        for p in postings:
            title = (p.get("title") or "").strip()
            external_path = (p.get("externalPath") or "").strip()
            bullet_fields = p.get("bulletFields") or []

            req_id = bullet_fields[0] if bullet_fields else ""
            if not req_id and external_path:
                req_id = external_path.split("_")[-1] if "_" in external_path else ""

            job_id = req_id or external_path.rstrip("/").split("/")[-1]
            if not job_id or not title or job_id in seen_ids:
                continue

            locations_text = (p.get("locationsText") or "").strip()
            if target_country_lower not in locations_text.lower() and target_country_lower not in external_path.lower():
                continue

            link = f"https://cohesity.wd5.myworkdayjobs.com/en-US/Cohesity_Careers{external_path}" if external_path else self.TARGET_URL
            location = locations_text if "india" in locations_text.lower() else f"{locations_text}, India"

            seen_ids.add(job_id)
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
        """Scrapes Cohesity open positions via high-performance curl_cffi AsyncSession."""
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.TARGET_URL,
        }

        async with AsyncSession(impersonate="chrome120") as s:
            # 1. Primary: Cohesity open-positions endpoint
            try:
                resp = await s.get(self.API_URL, headers=headers, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    # Check if undergoing Workday maintenance
                    if not data.get("workdayMaintenance"):
                        listings = self._parse_job_data(data, seen_ids)
                        if listings:
                            logger.info(f"Cohesity curl API scraped {len(listings)} engineering jobs in India.")
                            return listings
                    else:
                        logger.warning("Cohesity site indicates workdayMaintenance. Trying direct Workday endpoint...")
            except Exception as e:
                logger.warning(f"Cohesity primary API request failed: {e}. Trying Workday CXS backup...")

            # 2. Secondary fallback: Direct Workday CXS search
            try:
                wd_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": headers["User-Agent"],
                }
                wd_payload = {
                    "appliedFacets": {},
                    "limit": 50,
                    "offset": 0,
                    "searchText": "India",
                }
                wd_resp = await s.post(self.WORKDAY_API_URL, json=wd_payload, headers=wd_headers, timeout=25)
                if wd_resp.status_code == 200:
                    wd_data = wd_resp.json()
                    listings = self._parse_workday_backup(wd_data, seen_ids)
                    if listings:
                        logger.info(f"Cohesity Workday backup scraped {len(listings)} jobs.")
                        return listings
            except Exception as e:
                logger.warning(f"Cohesity Workday backup scrape failed: {e}")

        return []

    async def _scrape_playwright(self) -> List[JobListing]:
        """Low-RAM Playwright fallback using Chromium request context with stealth."""
        logger.info("Attempting Cohesity Careers scraping via Playwright fallback...")
        seen_ids: Set[str] = set()
        listings: List[JobListing] = []
        playwright_obj = None
        browser = None

        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                    "--disable-extensions",
                    "--js-flags=--max-old-space-size=128",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page = await context.new_page()
            await page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver;")

            # Attempt direct API fetch via Playwright request API
            api_resp = await page.request.get(
                self.API_URL,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": self.TARGET_URL,
                },
                timeout=30000,
            )
            if api_resp.status == 200:
                data = await api_resp.json()
                listings = self._parse_job_data(data, seen_ids)

        except Exception as e:
            logger.error(f"Playwright scraping error for Cohesity: {e}")
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

        logger.info(f"Cohesity Playwright scraped {len(listings)} engineering jobs in India.")
        return listings

    async def scrape(self) -> List[JobListing]:
        """Scrapes Cohesity Engineering jobs in India with curl primary and Playwright fallback."""
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Cohesity curl scrape returned 0 jobs. Falling back to Playwright...")
        except Exception as e:
            logger.error(f"Cohesity curl scrape failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Cohesity Playwright scrape failed: {e}")
            return []
