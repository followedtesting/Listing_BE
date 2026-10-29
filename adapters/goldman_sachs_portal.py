import gc
import json
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class GoldmanSachsPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "goldman_sachs_careers"

    @property
    def portal_name(self) -> str:
        return "Goldman Sachs Careers Portal"

    def _get_payload(self, page_number: int, page_size: int) -> dict:
        return {
            "operationName": "GetRoles",
            "variables": {
                "searchQueryInput": {
                    "page": {
                        "pageSize": page_size,
                        "pageNumber": page_number
                    },
                    "sort": {
                        "sortStrategy": "RELEVANCE",
                        "sortOrder": "DESC"
                    },
                    "filters": [
                        {
                            "filterCategoryType": "EXPERIENCE_LEVEL",
                            "filters": [
                                {
                                    "filter": "Analyst",
                                    "subFilters": []
                                }
                            ]
                        },
                        {
                            "filterCategoryType": "LOCATION",
                            "filters": [
                                {
                                    "filter": "India",
                                    "subFilters": [
                                        {
                                            "filter": "Karnataka",
                                            "subFilters": [
                                                {
                                                    "filter": "Bengaluru",
                                                    "subFilters": []
                                                }
                                            ]
                                        },
                                        {
                                            "filter": "Maharashtra",
                                            "subFilters": [
                                                {
                                                    "filter": "Mumbai",
                                                    "subFilters": []
                                                }
                                            ]
                                        },
                                        {
                                            "filter": "Telangana",
                                            "subFilters": [
                                                {
                                                    "filter": "Hyderabad",
                                                    "subFilters": []
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                    "experiences": [
                        "EARLY_CAREER",
                        "PROFESSIONAL"
                    ],
                    "searchTerm": "software engineering"
                }
            },
            "query": (
                "query GetRoles($searchQueryInput: RoleSearchQueryInput!) {\n"
                "  roleSearch(searchQueryInput: $searchQueryInput) {\n"
                "    totalCount\n"
                "    items {\n"
                "      roleId\n"
                "      corporateTitle\n"
                "      jobTitle\n"
                "      jobFunction\n"
                "      locations {\n"
                "        primary\n"
                "        state\n"
                "        country\n"
                "        city\n"
                "        __typename\n"
                "      }\n"
                "      status\n"
                "      division\n"
                "      skills\n"
                "      jobType {\n"
                "        code\n"
                "        description\n"
                "        __typename\n"
                "      }\n"
                "      externalSource {\n"
                "        sourceId\n"
                "        __typename\n"
                "      }\n"
                "      __typename\n"
                "    }\n"
                "    __typename\n"
                "  }\n"
                "}"
            )
        }

    def _parse_items(self, items: list, seen_ids: Set[str]) -> tuple[List[JobListing], bool]:
        listings = []
        duplicate_found = False
        for item in items:
            ext_source = item.get("externalSource", {})
            source_id = ext_source.get("sourceId") if isinstance(ext_source, dict) else None
            jobid = str(source_id or item.get("roleId", "")).strip()
            title = (item.get("jobTitle") or "").strip()

            if jobid and title:
                if jobid in seen_ids:
                    duplicate_found = True
                    break

                seen_ids.add(jobid)
                job_link = f"https://higher.gs.com/roles/{jobid}"
                locs = item.get("locations") or []
                loc = "India"
                if locs and isinstance(locs, list):
                    city = locs[0].get("city")
                    country = locs[0].get("country")
                    loc = f"{city}, {country}".strip(", ") if city else "India"

                listings.append(
                    JobListing(
                        jobid=jobid,
                        role_name=title,
                        job_listing_link=job_link,
                        location=loc,
                    )
                )
        return listings, duplicate_found

    async def _scrape_curl(self) -> List[JobListing]:
        api_url = "https://api-higher.gs.com/gateway/api/v1/graphql"
        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": "https://higher.gs.com",
            "Referer": "https://higher.gs.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        page_number = 0
        page_size = 20
        max_pages = 25

        async with AsyncSession(impersonate="chrome124") as s:
            while page_number < max_pages:
                payload = self._get_payload(page_number, page_size)
                resp = await s.post(api_url, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Goldman Sachs API returned status {resp.status_code} at page {page_number}")
                    break

                result = resp.json()
                data_obj = result.get("data", {})
                if not data_obj:
                    break

                role_search = data_obj.get("roleSearch", {})
                total_count = role_search.get("totalCount", 0)
                items = role_search.get("items", [])
                if not items:
                    break

                new_listings, duplicate_found = self._parse_items(items, seen_ids)
                listings.extend(new_listings)

                if duplicate_found or len(items) < page_size or (total_count and len(seen_ids) >= total_count):
                    break

                page_number += 1

        logger.info(f"Goldman Sachs curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Goldman Sachs...")
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
                await page.goto("https://higher.gs.com/results", wait_until="domcontentloaded", timeout=30000)

                page_number = 0
                page_size = 20
                max_pages = 25
                api_url = "https://api-higher.gs.com/gateway/api/v1/graphql"

                while page_number < max_pages:
                    payload = self._get_payload(page_number, page_size)

                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    method: 'POST',
                                    headers: {{ 'Content-Type': 'application/json' }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)

                    if not result or "error" in result:
                        break

                    data_obj = result.get("data", {})
                    if not data_obj:
                        break

                    role_search = data_obj.get("roleSearch", {})
                    total_count = role_search.get("totalCount", 0)
                    items = role_search.get("items", [])
                    if not items:
                        break

                    new_listings, duplicate_found = self._parse_items(items, seen_ids)
                    listings.extend(new_listings)

                    if duplicate_found or len(items) < page_size or (total_count and len(seen_ids) >= total_count):
                        break

                    page_number += 1
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"Goldman Sachs curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
