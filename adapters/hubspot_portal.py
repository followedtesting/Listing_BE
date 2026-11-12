import asyncio
import gc
import json
import logging
from typing import List, Set, Dict, Any, Optional
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class HubSpotPortalAdapter(BaseJobAdapter):
    """
    Adapter for HubSpot Careers Portal.
    Target URL: https://www.hubspot.com/careers/jobs?hubs_signup-cta=careers-nav-cta&page=1#office=bengaluru,remote;department=product-ux-engineering;
    
    Filters:
      - Office: Bengaluru, India & Remote
      - Department: Product, UX & Engineering
      
    Network Architecture:
      - Primary: POST https://wtcfns.hubspot.com/careers/graphql (fast GraphQL endpoint)
      - Secondary Fallback: Headless Playwright browser automation
    """

    TARGET_URL = "https://www.hubspot.com/careers/jobs?hubs_signup-cta=careers-nav-cta&page=1#office=bengaluru,remote;department=product-ux-engineering;"
    BASE_URL = "https://www.hubspot.com"
    GRAPHQL_URL = "https://wtcfns.hubspot.com/careers/graphql"

    # Filter mappings extracted from HubSpot careers directory bundle:
    # productEngineering: { label: "Product, UX & Engineering", id: [9908, 63933, 63932, 64162], param: "product-ux-engineering" }
    TARGET_DEPARTMENT_IDS = {9908, 63933, 63932, 64162}
    DEPARTMENT_KEYWORDS = ["product", "ux", "engineering"]

    # bengaluru: { id: 172812, label: "Bengaluru, India", param: "bengaluru" }
    # remote: { id: [43769, 57033, 61530, 43765, 43767, 43770, 43768, 43766, 80765, 80764, 85797, 85799, 85798, 88301, 88305], label: "Remote", param: "remote" }
    TARGET_OFFICE_IDS = {
        172812, 43769, 57033, 61530, 43765, 43767, 43770, 43768, 43766,
        80765, 80764, 85797, 85799, 85798, 88301, 88305
    }
    OFFICE_KEYWORDS = ["bengaluru", "bangalore", "remote"]

    @property
    def portal_id(self) -> str:
        return "hubspot_careers"

    @property
    def portal_name(self) -> str:
        return "HubSpot Careers Portal"

    def _matches_filters(self, job: Dict[str, Any]) -> bool:
        """Checks if a job item satisfies the office and department filters."""
        # 1. Department match
        dept = job.get("department") or {}
        dept_id = dept.get("id")
        dept_name = (dept.get("name") or "").lower()

        dept_matched = False
        if dept_id in self.TARGET_DEPARTMENT_IDS:
            dept_matched = True
        elif any(k in dept_name for k in self.DEPARTMENT_KEYWORDS):
            dept_matched = True

        if not dept_matched:
            return False

        # 2. Office / Location match
        office = job.get("office") or {}
        office_id = office.get("id")
        office_loc = (office.get("location") or office.get("name") or "").lower()
        loc_name = (job.get("location", {}).get("name") or "").lower()

        office_matched = False
        if office_id in self.TARGET_OFFICE_IDS:
            office_matched = True
        elif any(k in office_loc for k in self.OFFICE_KEYWORDS) or any(k in loc_name for k in self.OFFICE_KEYWORDS):
            office_matched = True

        return office_matched

    def _parse_job_items(self, jobs: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        """Parses a list of GraphQL job dicts into JobListing instances."""
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

            # Verify department and location criteria
            if not self._matches_filters(j):
                continue

            seen_ids.add(job_id)

            # Location formatting
            office = j.get("office") or {}
            loc_obj = j.get("location") or {}
            location = (office.get("location") or office.get("name") or loc_obj.get("name") or "Remote / Bengaluru").strip()

            # Absolute URL
            job_link = (j.get("absolute_url") or "").strip()
            if not job_link or not job_link.startswith("http"):
                job_link = f"{self.BASE_URL}/careers/jobs/{job_id}?gh_jid={job_id}"

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=job_link,
                    location=location,
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes HubSpot Careers via high-performance GraphQL requests using curl_cffi."""
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": self.BASE_URL,
            "Referer": self.TARGET_URL,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124") as session:
            # First attempt: Parameterized query matching frontend variables
            param_query = (
                "query Jobs($departmentIds: [Int], $officeIds: [Int], $languages: [String], $roleTypes: [String], $searchQuery: String) {\n"
                "  jobs(departmentIds: $departmentIds, officeIds: $officeIds, languages: $languages, roleTypes: $roleTypes, searchQuery: $searchQuery) {\n"
                "    id\n"
                "    title\n"
                "    absolute_url\n"
                "    updated_at\n"
                "    department {\n"
                "      id\n"
                "      name\n"
                "    }\n"
                "    office {\n"
                "      id\n"
                "      name\n"
                "      location\n"
                "    }\n"
                "    location {\n"
                "      name\n"
                "    }\n"
                "  }\n"
                "}\n"
            )

            payload = {
                "operationName": "Jobs",
                "variables": {
                    "departmentIds": sorted(list(self.TARGET_DEPARTMENT_IDS)),
                    "officeIds": sorted(list(self.TARGET_OFFICE_IDS)),
                    "languages": [],
                    "roleTypes": []
                },
                "query": param_query
            }

            try:
                resp = await session.post(self.GRAPHQL_URL, json=payload, headers=headers, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    jobs = data.get("data", {}).get("jobs", [])
                    listings = self._parse_job_items(jobs, seen_ids)
                    if listings:
                        logger.info(f"HubSpot GraphQL parameterized query returned {len(listings)} listings")
                        return listings
            except Exception as e:
                logger.warning(f"HubSpot GraphQL parameterized query error: {e}")

            # Second attempt: Query full jobs list and filter locally
            full_query = (
                "query {\n"
                "  jobs {\n"
                "    id\n"
                "    title\n"
                "    absolute_url\n"
                "    updated_at\n"
                "    department {\n"
                "      id\n"
                "      name\n"
                "    }\n"
                "    office {\n"
                "      id\n"
                "      name\n"
                "      location\n"
                "    }\n"
                "    location {\n"
                "      name\n"
                "    }\n"
                "  }\n"
                "}\n"
            )

            try:
                resp = await session.post(self.GRAPHQL_URL, json={"query": full_query}, headers=headers, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    jobs = data.get("data", {}).get("jobs", [])
                    listings = self._parse_job_items(jobs, seen_ids)
                    logger.info(f"HubSpot GraphQL full query filtered to {len(listings)} listings")
                    return listings
            except Exception as e:
                logger.warning(f"HubSpot GraphQL full query error: {e}")

        return []

    async def _scrape_playwright(self) -> List[JobListing]:
        """Low-RAM Playwright fallback to scrape HubSpot Careers portal."""
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

                # Intercept GraphQL responses during navigation
                captured_jobs: List[Dict[str, Any]] = []

                async def on_response(response):
                    if "careers/graphql" in response.url and response.status == 200:
                        try:
                            res_json = await response.json()
                            batch = res_json.get("data", {}).get("jobs", [])
                            if batch:
                                captured_jobs.extend(batch)
                        except Exception:
                            pass

                page.on("response", on_response)

                logger.info(f"Navigating to HubSpot Careers URL: {self.TARGET_URL}")
                await page.goto(self.TARGET_URL, wait_until="commit", timeout=30000)

                # Wait for GraphQL response or job card rendering
                for _ in range(12):
                    await asyncio.sleep(1)
                    if captured_jobs:
                        break

                if captured_jobs:
                    listings = self._parse_job_items(captured_jobs, seen_ids)
                    if listings:
                        return listings

                # Fallback: inspect DOM for rendered apply buttons or job links
                job_elements = await page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/careers/jobs/"]'));
                    return links.map(a => {
                        const href = a.getAttribute('href') || '';
                        const card = a.closest('.careers-directory__job-item, tr, li, div') || a;
                        const titleEl = card.querySelector('h3, h4, .job-title, [class*="title"]') || a;
                        return {
                            href: href,
                            title: titleEl ? titleEl.innerText.trim() : a.innerText.trim(),
                            text: card.innerText.trim()
                        };
                    });
                }""")

                for el in job_elements:
                    href = el.get("href", "")
                    title = el.get("title", "")
                    if not href or not title:
                        continue

                    # Extract job ID from href (e.g. /careers/jobs/8073610?...)
                    import re
                    m = re.search(r"/jobs/(\d+)", href)
                    job_id = m.group(1) if m else href

                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                    listings.append(
                        JobListing(
                            jobid=str(job_id),
                            role_name=title,
                            job_listing_link=full_url,
                            location="Remote / Bengaluru",
                        )
                    )

        except Exception as e:
            logger.error(f"Playwright scraping failed for HubSpot portal: {e}")
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
        """Main entry point: Attempts high-speed curl_cffi GraphQL first, then falls back to Playwright."""
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"HubSpot portal successfully scraped {len(listings)} jobs via curl_cffi")
                return listings
            logger.warning("HubSpot curl_cffi returned 0 listings, falling back to Playwright")
        except Exception as e:
            logger.warning(f"HubSpot curl_cffi failed ({e}), falling back to Playwright")

        listings = await self._scrape_playwright()
        logger.info(f"HubSpot portal scraped {len(listings)} jobs via Playwright fallback")
        return listings
