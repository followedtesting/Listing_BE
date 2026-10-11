import json
import logging
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NationwidePortalAdapter(BaseJobAdapter):
    """
    Adapter for Nationwide India Careers (Workday).
    Target URL: https://nationwide.wd1.myworkdayjobs.com/Nationwide_Career_India
    """

    TARGET_URL = "https://nationwide.wd1.myworkdayjobs.com/Nationwide_Career_India"
    API_URL = "https://nationwide.wd1.myworkdayjobs.com/wday/cxs/nationwide/Nationwide_Career_India/jobs"

    @property
    def portal_id(self) -> str:
        return "nationwide_careers"

    @property
    def portal_name(self) -> str:
        return "Nationwide Careers (Workday)"

    def _parse_job_postings(self, postings: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for job in postings:
            title = (job.get("title") or "").strip()
            ext_path = (job.get("externalPath") or "").strip()
            bullets = job.get("bulletFields") or []

            # Extract requisition / job ID
            job_id = None
            for b in bullets:
                if isinstance(b, str) and (b.startswith("JR") or b.startswith("REQ") or b.startswith("R") or b.isdigit()):
                    job_id = b.strip()
                    break

            # Fallback to suffix in externalPath (e.g. Consultant_100371 -> 100371)
            if not job_id and ext_path:
                id_match = re.search(r"_([A-Za-z0-9_-]+)$", ext_path)
                if id_match:
                    job_id = id_match.group(1).strip()
                else:
                    job_id = ext_path.rstrip("/").split("/")[-1]

            if not job_id or not title or job_id in seen_ids:
                continue

            # Location: from locationsText or bulletFields or default to India
            loc_text = (job.get("locationsText") or "").strip()
            if not loc_text and bullets and isinstance(bullets[0], str):
                loc_text = bullets[0].strip()
            if not loc_text:
                loc_text = "Hyderabad, India"

            seen_ids.add(job_id)
            full_link = f"https://nationwide.wd1.myworkdayjobs.com/en-US/Nationwide_Career_India{ext_path}"
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location=loc_text,
                )
            )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.TARGET_URL,
            "Origin": "https://nationwide.wd1.myworkdayjobs.com",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        total_count = None

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                payload = {
                    "appliedFacets": {},
                    "limit": limit,
                    "offset": offset,
                    "searchText": "",
                }

                resp = await session.post(self.API_URL, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Nationwide Workday API returned HTTP {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                if total_count is None and "total" in data:
                    total_count = data.get("total")

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch_listings = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch_listings)

                offset += len(postings)
                if total_count is not None and offset >= total_count:
                    break
                if len(postings) < limit:
                    break

        logger.info(f"Nationwide curl scraped {len(listings)} jobs.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Nationwide scraping via Playwright fallback...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        total_count = None

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
                await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=40000)
                await asyncio.sleep(2)

                while True:
                    payload = {
                        "appliedFacets": {},
                        "limit": limit,
                        "offset": offset,
                        "searchText": "",
                    }

                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{self.API_URL}', {{
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
                        logger.error(f"Error fetching Nationwide Workday jobs at offset {offset}: {data}")
                        break

                    if total_count is None and "total" in data:
                        total_count = data.get("total")

                    postings = data.get("jobPostings", [])
                    if not postings:
                        break

                    batch_listings = self._parse_job_postings(postings, seen_ids)
                    listings.extend(batch_listings)

                    offset += len(postings)
                    if total_count is not None and offset >= total_count:
                        break
                    if len(postings) < limit:
                        break

                logger.info(f"Nationwide Playwright scraped {len(listings)} jobs.")
            except Exception as e:
                logger.error(f"Playwright scraping error for Nationwide: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. High performance curl_cffi direct Workday CXS API
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Nationwide curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"Nationwide curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright in-browser fetch fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Nationwide Playwright scraping failed: {e}")
            return []
