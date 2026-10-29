import gc
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AmexPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "amex_careers"

    @property
    def portal_name(self) -> str:
        return "American Express Careers (Oracle HCM)"

    def _parse_postings(self, postings: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for job in postings:
            job_id = str(job.get("Id") or job.get("RequisitionId") or "").strip()
            title = (job.get("Title") or "").strip()

            if job_id and title and job_id not in seen_ids:
                seen_ids.add(job_id)
                full_link = f"https://careers.americanexpress.com/en/sites/CX_1/job/{job_id}"
                loc = job.get("PrimaryLocation") or "India"
                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=full_link,
                        location=loc,
                    )
                )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 25

        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://careers.americanexpress.com/en/sites/CX_1/jobs",
        }

        async with AsyncSession(impersonate="chrome124") as s:
            while True:
                api_url = (
                    f"https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                    f"?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields"
                    f"&finder=findReqs;siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,"
                    f"limit={limit},offset={offset},lastSelectedFacet=AttributeChar6,locationId=300000000228786,selectedFlexFieldsFacets=%22AttributeChar6%7CTechnology%22,sortBy=POSTING_DATES_DESC"
                )

                resp = await s.get(api_url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"AMEX Oracle HCM API returned {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                if not isinstance(data, dict) or "items" not in data or not data["items"]:
                    break

                req_container = data["items"][0]
                total_jobs = req_container.get("TotalJobsCount", 0)
                postings = req_container.get("requisitionList", [])
                if not postings:
                    break

                batch_listings = self._parse_postings(postings, seen_ids)
                listings.extend(batch_listings)

                if len(postings) < limit or offset + len(postings) >= total_jobs:
                    break

                offset += limit

        logger.info(f"AMEX curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for AMEX...")
        target_url = "https://careers.americanexpress.com/en/sites/CX_1/jobs"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 25

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

                while True:
                    api_url = (
                        f"https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                        f"?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields"
                        f"&finder=findReqs;siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,"
                        f"limit={limit},offset={offset},lastSelectedFacet=AttributeChar6,locationId=300000000228786,selectedFlexFieldsFacets=%22AttributeChar6%7CTechnology%22,sortBy=POSTING_DATES_DESC"
                    )

                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    headers: {{ 'Accept': 'application/json, text/plain, */*' }}
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)

                    if not isinstance(data, dict) or "items" not in data or not data["items"]:
                        break

                    req_container = data["items"][0]
                    total_jobs = req_container.get("TotalJobsCount", 0)
                    postings = req_container.get("requisitionList", [])
                    if not postings:
                        break

                    batch_listings = self._parse_postings(postings, seen_ids)
                    listings.extend(batch_listings)

                    if len(postings) < limit or offset + len(postings) >= total_jobs:
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
            logger.warning(f"AMEX curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
