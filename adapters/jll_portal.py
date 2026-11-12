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


class JLLPortalAdapter(BaseJobAdapter):
    """
    Adapter for JLL Careers Portal (Workday).
    Target URL: https://jll.wd1.myworkdayjobs.com/en-GB/jllcareers?locationCountry=c4f78be1a8f14da0ab49ce1162348a5e&jobFamilyGroup=c608fc06410f01484a9fec7aba539450&jobFamilyGroup=f134f8e1c0811001fe9e2695d0c80000&jobFamilyGroup=b433b91436a91001fe918431478f0000&jobFamilyGroup=ee1ccf9903501001feb0e7ffc6680000
    Filters:
      - Country: India (locationCountry: c4f78be1a8f14da0ab49ce1162348a5e)
      - Job Family Groups:
        - c608fc06410f01484a9fec7aba539450
        - f134f8e1c0811001fe9e2695d0c80000
        - b433b91436a91001fe918431478f0000
        - ee1ccf9903501001feb0e7ffc6680000
    """

    TARGET_URL = (
        "https://jll.wd1.myworkdayjobs.com/en-GB/jllcareers"
        "?locationCountry=c4f78be1a8f14da0ab49ce1162348a5e"
        "&jobFamilyGroup=c608fc06410f01484a9fec7aba539450"
        "&jobFamilyGroup=f134f8e1c0811001fe9e2695d0c80000"
        "&jobFamilyGroup=b433b91436a91001fe918431478f0000"
        "&jobFamilyGroup=ee1ccf9903501001feb0e7ffc6680000"
    )
    API_URL = "https://jll.wd1.myworkdayjobs.com/wday/cxs/jll/jllcareers/jobs"
    BASE_JOB_URL = "https://jll.wd1.myworkdayjobs.com/en-GB/jllcareers"

    APPLIED_FACETS = {
        "locationCountry": ["c4f78be1a8f14da0ab49ce1162348a5e"],
        "jobFamilyGroup": [
            "c608fc06410f01484a9fec7aba539450",
            "f134f8e1c0811001fe9e2695d0c80000",
            "b433b91436a91001fe918431478f0000",
            "ee1ccf9903501001feb0e7ffc6680000",
        ],
    }

    @property
    def portal_id(self) -> str:
        return "jll_careers"

    @property
    def portal_name(self) -> str:
        return "JLL Careers Portal (Workday)"

    def _parse_job_postings(self, postings: list, seen_ids: Set[str]) -> List[JobListing]:
        """Parses Workday job postings into JobListing instances."""
        listings: List[JobListing] = []
        for job in postings:
            title = (job.get("title") or "").strip()
            ext_path = (job.get("externalPath") or "").strip()
            bullets = job.get("bulletFields") or []

            # Extract requisition / job ID
            job_id = None
            for b in bullets:
                if isinstance(b, str) and (
                    b.startswith("REQ") or b.startswith("JR") or b.startswith("R") or b.isdigit()
                ):
                    job_id = b.strip()
                    break

            # Fallback to suffix in externalPath (e.g. Software-Engineer-2_REQ506256 -> REQ506256)
            if not job_id and ext_path:
                id_match = re.search(r"_([A-Za-z0-9_-]+)$", ext_path)
                if id_match:
                    job_id = id_match.group(1).strip()
                else:
                    job_id = ext_path.rstrip("/").split("/")[-1]

            if not job_id or not title or job_id in seen_ids:
                continue

            # Format location
            loc_text = (job.get("locationsText") or "").strip()
            if not loc_text and bullets and isinstance(bullets[0], str):
                loc_text = bullets[0].strip()
            if not loc_text:
                loc_text = "India"
            elif "india" not in loc_text.lower():
                loc_text = f"{loc_text}, India"

            seen_ids.add(job_id)
            full_link = f"{self.BASE_JOB_URL}{ext_path}" if ext_path else self.TARGET_URL
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
        """Scrapes JLL Workday CXS API using high-performance curl_cffi."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.TARGET_URL,
            "Origin": "https://jll.wd1.myworkdayjobs.com",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        total_count = None

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                payload = {
                    "appliedFacets": self.APPLIED_FACETS,
                    "limit": limit,
                    "offset": offset,
                    "searchText": "",
                }

                resp = await session.post(self.API_URL, json=payload, headers=headers, timeout=25)
                if resp.status_code != 200:
                    logger.warning(f"JLL Workday API returned HTTP {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                if total_count is None and "total" in data:
                    total_count = data.get("total")

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch)

                offset += len(postings)
                if total_count is not None and offset >= total_count:
                    break
                if len(postings) < limit:
                    break

        logger.info(f"JLL curl scraped {len(listings)} jobs (total: {total_count}).")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Low-RAM Playwright fallback for JLL Workday."""
        logger.info("Attempting JLL scraping via Playwright fallback...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        total_count = None
        playwright_obj = None
        browser = None

        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
                headless=True,
                args=[
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

            # Abort heavy static assets to conserve RAM
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort(),
            )

            await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(2)

            while True:
                payload = {
                    "appliedFacets": self.APPLIED_FACETS,
                    "limit": limit,
                    "offset": offset,
                    "searchText": "",
                }

                data = await page.evaluate(
                    f"""
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
                    """
                )

                if not isinstance(data, dict) or "error" in data:
                    logger.error(f"Error fetching JLL Workday jobs in Playwright at offset {offset}: {data}")
                    break

                if total_count is None and "total" in data:
                    total_count = data.get("total")

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch)

                offset += len(postings)
                if total_count is not None and offset >= total_count:
                    break
                if len(postings) < limit:
                    break

            logger.info(f"JLL Playwright scraped {len(listings)} jobs.")
        except Exception as e:
            logger.error(f"Playwright scraping error for JLL: {e}", exc_info=True)
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

        return listings

    async def scrape(self) -> List[JobListing]:
        """Scrapes JLL listings with curl primary and Playwright fallback."""
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("JLL curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"JLL curl scraping failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"JLL Playwright scraping failed: {e}")
            return []
