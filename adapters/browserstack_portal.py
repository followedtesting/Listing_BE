import json
import logging
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class BrowserStackPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "browserstack_careers"

    @property
    def portal_name(self) -> str:
        return "BrowserStack Careers (Workday)"

    def _parse_job_postings(self, postings: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for job in postings:
            title = (job.get("title") or "").strip()
            ext_path = (job.get("externalPath") or "").strip()
            loc_text = (job.get("locationsText") or "India Remote").strip()
            bullets = job.get("bulletFields", [])

            # Extract requisition / job ID
            job_id = None
            for b in bullets:
                if b.startswith("JR") or b.startswith("REQ") or b.startswith("R") or b.isdigit():
                    job_id = b
                    break

            # Fallback to suffix in externalPath (e.g. Engineering-Manager_JR103738-1 -> JR103738-1)
            if ext_path:
                id_match = re.search(r"_([A-Za-z0-9_-]+)$", ext_path)
                if id_match:
                    job_id = id_match.group(1)
                elif not job_id:
                    job_id = ext_path.rstrip("/").split("/")[-1]

            if not job_id or not title or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            full_link = f"https://browserstack.wd3.myworkdayjobs.com/en-US/External{ext_path}"
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location=loc_text
                )
            )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        api_url = "https://browserstack.wd3.myworkdayjobs.com/wday/cxs/browserstack/External/jobs"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://browserstack.wd3.myworkdayjobs.com/External?locations=07564020a4451005a3027f2ca2d60000&jobFamilyGroup=0cb9174e33c9100190f156427de80000",
            "Origin": "https://browserstack.wd3.myworkdayjobs.com",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                payload = {
                    "appliedFacets": {
                        "locations": ["07564020a4451005a3027f2ca2d60000"],
                        "jobFamilyGroup": ["0cb9174e33c9100190f156427de80000"]
                    },
                    "limit": limit,
                    "offset": offset,
                    "searchText": ""
                }

                resp = await session.post(api_url, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"BrowserStack Workday API returned HTTP {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                total = data.get("total", 0)
                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch_listings = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch_listings)

                offset += limit
                if offset >= total:
                    break

        logger.info(f"BrowserStack curl scraped {len(listings)} jobs.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting BrowserStack scraping via Playwright...")
        target_url = "https://browserstack.wd3.myworkdayjobs.com/External?locations=07564020a4451005a3027f2ca2d60000&jobFamilyGroup=0cb9174e33c9100190f156427de80000"
        wday_endpoint = "https://browserstack.wd3.myworkdayjobs.com/wday/cxs/browserstack/External/jobs"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20

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
                        "appliedFacets": {
                            "locations": ["07564020a4451005a3027f2ca2d60000"],
                            "jobFamilyGroup": ["0cb9174e33c9100190f156427de80000"]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }

                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{wday_endpoint}', {{
                                    method: 'POST',
                                    headers: {{
                                        'Content-Type': 'application/json',
                                        'Accept': 'application/json'
                                    }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)

                    if not isinstance(data, dict) or "error" in data:
                        logger.error(f"Error fetching BrowserStack Workday jobs at offset {offset}: {data}")
                        break

                    total = data.get("total", 0)
                    postings = data.get("jobPostings", [])
                    if not postings:
                        break

                    batch_listings = self._parse_job_postings(postings, seen_ids)
                    listings.extend(batch_listings)

                    offset += limit
                    if offset >= total:
                        break

                logger.info(f"BrowserStack Playwright scraped {len(listings)} jobs.")
            except Exception as e:
                logger.error(f"Playwright scraping error for BrowserStack: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. High performance curl_cffi direct Workday CXS API
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("BrowserStack curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"BrowserStack curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright in-browser fetch fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"BrowserStack Playwright scraping failed: {e}")
            return []
