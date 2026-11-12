import gc
import json
import logging
from typing import List, Set, Dict, Any
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class InforPortalAdapter(BaseJobAdapter):
    """
    Adapter for Infor Careers Portal (Pinpoint ATS).
    Target URL: https://careers.infor.com/?structure_custom_group_one_id=%5B11296%5D&department_id=%5B72508%5D
    Filters:
      - Country (structure_custom_group_one_id): 11296 ("India")
      - Department (department_id): 72508 ("Development")
    """

    TARGET_URL = "https://careers.infor.com/?structure_custom_group_one_id=%5B11296%5D&department_id=%5B72508%5D"
    API_URL = "https://careers.infor.com/postings.json"

    DEPARTMENT_ID = "72508"  # Development
    COUNTRY_ID = "11296"     # India

    @property
    def portal_id(self) -> str:
        return "infor_careers"

    @property
    def portal_name(self) -> str:
        return "Infor Careers Portal"

    def _parse_postings(self, data: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        listings: List[JobListing] = []

        for item in data:
            job = item.get("job") or {}
            dept = job.get("department") or {}
            group1 = job.get("structure_custom_group_one") or {}

            # Filter by Department ID: 72508 ("Development")
            dept_id = str(dept.get("id") or "").strip()
            dept_name = (dept.get("name") or "").strip().lower()
            is_dept_match = dept_id == self.DEPARTMENT_ID or dept_name == "development"

            # Filter by Country / Structure Custom Group One ID: 11296 ("India")
            country_id = str(group1.get("id") or "").strip()
            country_name = (group1.get("name") or "").strip().lower()
            is_country_match = country_id == self.COUNTRY_ID or country_name == "india"

            if not (is_dept_match and is_country_match):
                continue

            # Extract job ID (prefer requisition_id, fallback to internal id, then uuid in URL)
            job_id = job.get("requisition_id")
            if not job_id:
                job_id = str(item.get("id") or "")
            if not job_id and item.get("url"):
                job_id = item.get("url", "").rstrip("/").split("/")[-1]

            job_id = str(job_id).strip()
            title = (item.get("title") or "").strip()
            link = (item.get("url") or "").strip()

            if not link and item.get("path"):
                link = f"https://careers.infor.com{item.get('path')}"

            # Location formatting
            loc_dict = item.get("location") or {}
            loc_name = loc_dict.get("name") or loc_dict.get("city") or "India"
            if "india" not in loc_name.lower():
                location = f"{loc_name}, India"
            else:
                location = loc_name

            if job_id and title and job_id not in seen_ids:
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
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.TARGET_URL,
        }

        async with AsyncSession(impersonate="chrome120") as s:
            resp = await s.get(self.API_URL, headers=headers, timeout=25)
            if resp.status_code != 200:
                logger.warning(f"Infor postings API returned HTTP {resp.status_code}")
                return []

            data = resp.json()
            postings = data.get("data", [])
            listings = self._parse_postings(postings, seen_ids)

        logger.info(f"Infor curl scraped {len(listings)} jobs.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Infor Careers scraping via Playwright fallback...")
        seen_ids: Set[str] = set()
        listings: List[JobListing] = []
        playwright_obj = None
        browser = None

        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
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
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            # Abort heavy assets
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,mp4,webm}",
                lambda route: route.abort()
            )

            await page.goto(self.API_URL, wait_until="domcontentloaded", timeout=30000)
            content = await page.inner_text("body")
            data = json.loads(content)
            postings = data.get("data", [])
            listings = self._parse_postings(postings, seen_ids)

        except Exception as e:
            logger.error(f"Playwright fallback failed for Infor: {e}")
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

        logger.info(f"Infor Playwright scraped {len(listings)} jobs.")
        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Infor curl scrape returned 0 jobs. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"Infor curl scrape failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Infor Playwright scrape failed: {e}")
            return []
