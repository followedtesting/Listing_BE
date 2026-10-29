import gc
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AkamaiPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "akamai_careers"

    @property
    def portal_name(self) -> str:
        return "Akamai Careers Portal"

    def _parse_req_list(self, req_list: list, seen_ids: Set[str]) -> tuple[List[JobListing], bool]:
        listings = []
        duplicate_found = False
        for req in req_list:
            jobid = req.get("Id")
            title = req.get("Title")

            if jobid and title:
                jobid_str = str(jobid).strip()
                if jobid_str in seen_ids:
                    duplicate_found = True
                    break

                seen_ids.add(jobid_str)
                job_listing_link = f"https://jobs.akamai.com/en/sites/CX_1/job/{jobid_str}"
                loc = req.get("PrimaryLocation") or "India"

                listings.append(
                    JobListing(
                        jobid=jobid_str,
                        role_name=title.strip(),
                        job_listing_link=job_listing_link,
                        location=loc,
                    )
                )
        return listings, duplicate_found

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 25
        max_safety_limit = 200

        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://jobs.akamai.com/en/sites/CX_1/jobs",
        }

        async with AsyncSession(impersonate="chrome124") as s:
            while offset < max_safety_limit:
                rest_api_url = "https://fa-extu-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                finder = f"findReqs;siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit={limit},offset={offset},lastSelectedFacet=TITLES,locationId=300000000469285,selectedTitlesFacet=ENG,sortBy=POSTING_DATES_DESC"
                api_url = f"{rest_api_url}?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder={finder}"

                resp = await s.get(api_url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Akamai Oracle HCM API returned {resp.status_code} at offset {offset}")
                    break

                result = resp.json()
                items = result.get("items", [])
                if not items:
                    break

                req_list = items[0].get("requisitionList", [])
                if not req_list:
                    break

                new_listings, duplicate_found = self._parse_req_list(req_list, seen_ids)
                listings.extend(new_listings)

                if duplicate_found or len(req_list) < limit:
                    break

                offset += limit

        logger.info(f"Akamai curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Akamai...")
        target_url = "https://jobs.akamai.com/en/sites/CX_1/jobs"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 25
        max_safety_limit = 200

        async with async_playwright() as p:
            browser = await p.chromium.launch(
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
                ]
            )
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.route(
                    "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                    lambda route: route.abort()
                )
                await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

                while offset < max_safety_limit:
                    rest_api_url = "https://fa-extu-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                    finder = f"findReqs;siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit={limit},offset={offset},lastSelectedFacet=TITLES,locationId=300000000469285,selectedTitlesFacet=ENG,sortBy=POSTING_DATES_DESC"
                    api_url = f"{rest_api_url}?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder={finder}"

                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}');
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)

                    if not result or "error" in result:
                        break

                    items = result.get("items", [])
                    if not items:
                        break

                    req_list = items[0].get("requisitionList", [])
                    if not req_list:
                        break

                    new_listings, duplicate_found = self._parse_req_list(req_list, seen_ids)
                    listings.extend(new_listings)

                    if duplicate_found or len(req_list) < limit:
                        break

                    offset += limit
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"Akamai curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
