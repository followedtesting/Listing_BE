import json
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SnowflakePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "snowflake_careers"

    @property
    def portal_name(self) -> str:
        return "Snowflake Careers Portal"

    def _parse_job_items(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for j in jobs:
            job_id = j.get("jobId") or j.get("reqId")
            title = (j.get("title") or "").strip()

            if not job_id or not title:
                continue

            job_id_str = str(job_id).strip()
            if job_id_str in seen_ids:
                continue

            seen_ids.add(job_id_str)

            # Location formatting
            loc = (j.get("cityStateCountry") or j.get("location") or "").strip()
            if not loc:
                parts = [p.strip() for p in [j.get("city"), j.get("state"), j.get("country")] if p]
                loc = ", ".join(parts) if parts else "Remote"

            link = f"https://careers.snowflake.com/us/en/job/{job_id_str}"

            listings.append(
                JobListing(
                    jobid=job_id_str,
                    role_name=title,
                    job_listing_link=link,
                    location=loc
                )
            )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        url = "https://careers.snowflake.com/widgets"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://careers.snowflake.com",
            "Referer": "https://careers.snowflake.com/us/en/search-results?category=Engineering",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        size = 50

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                payload = {
                    "lang": "en_us",
                    "deviceType": "desktop",
                    "country": "us",
                    "pageName": "search-results",
                    "ddoKey": "refineSearch",
                    "sortBy": "",
                    "subsearch": "",
                    "from": offset,
                    "irs": False,
                    "jobs": True,
                    "counts": True,
                    "all_fields": ["category", "country", "state", "city"],
                    "size": size,
                    "clearAll": False,
                    "jdsource": "facets",
                    "isSliderEnable": False,
                    "pageId": "page11-ds",
                    "siteType": "external",
                    "keywords": "",
                    "global": True,
                    "selected_fields": {
                        "category": ["Engineering"]
                    },
                    "locationData": {}
                }

                resp = await session.post(url, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Snowflake Phenom API returned HTTP {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                refine = data.get("refineSearch", {})
                total = refine.get("totalHits", 0)
                jobs = refine.get("data", {}).get("jobs", [])
                if not jobs:
                    break

                batch = self._parse_job_items(jobs, seen_ids)
                listings.extend(batch)

                offset += size
                if offset >= total:
                    break

        logger.info(f"Snowflake curl scraped {len(listings)} Engineering jobs.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Snowflake scraping via Playwright...")
        target_url = "https://careers.snowflake.com/us/en/search-results?category=Engineering"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        size = 50

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)

                while True:
                    payload = {
                        "lang": "en_us",
                        "deviceType": "desktop",
                        "country": "us",
                        "pageName": "search-results",
                        "ddoKey": "refineSearch",
                        "sortBy": "",
                        "subsearch": "",
                        "from": offset,
                        "irs": False,
                        "jobs": True,
                        "counts": True,
                        "all_fields": ["category", "country", "state", "city"],
                        "size": size,
                        "clearAll": False,
                        "jdsource": "facets",
                        "isSliderEnable": False,
                        "pageId": "page11-ds",
                        "siteType": "external",
                        "keywords": "",
                        "global": True,
                        "selected_fields": {
                            "category": ["Engineering"]
                        },
                        "locationData": {}
                    }

                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const res = await fetch('/widgets', {{
                                    method: 'POST',
                                    headers: {{
                                        'Content-Type': 'application/json',
                                        'Accept': 'application/json'
                                    }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                return await res.json();
                            }} catch (e) {{
                                return {{ "error": e.message }};
                            }}
                        }}
                    """)

                    if not isinstance(data, dict) or "error" in data:
                        logger.error(f"Error fetching Snowflake jobs in-page at offset {offset}: {data}")
                        break

                    refine = data.get("refineSearch", {})
                    total = refine.get("totalHits", 0)
                    jobs = refine.get("data", {}).get("jobs", [])
                    if not jobs:
                        break

                    batch = self._parse_job_items(jobs, seen_ids)
                    listings.extend(batch)

                    offset += size
                    if offset >= total:
                        break

                logger.info(f"Snowflake Playwright scraped {len(listings)} Engineering jobs.")
            except Exception as e:
                logger.error(f"Playwright scraping error for Snowflake: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. High performance curl_cffi direct Phenom REST API
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Snowflake curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"Snowflake curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright in-browser fetch fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Snowflake Playwright scraping also failed: {e}")
            return []
