import logging
import asyncio
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SwiggyPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "swiggy_careers"

    @property
    def portal_name(self) -> str:
        return "Swiggy Careers Portal"

    def _parse_jobs(self, jobs: list, seen_ids: Set[str], target_unit: str = "Technology") -> List[JobListing]:
        listings = []
        unit_lower = target_unit.lower()

        for idx, j in enumerate(jobs):
            # Check unit filter: 'b' holds the Business Unit in Swiggy's jobs.json
            unit = str(j.get("b", "")).strip().lower()
            if unit != unit_lower:
                continue

            title = str(j.get("t", "")).strip()
            link = str(j.get("u", "")).strip()
            location = str(j.get("l", "")).strip() or str(j.get("c", "")).strip() or "India"

            # Extract SmartRecruiters Job ID from the link: /6000000001476176-software-dev...
            match = re.search(r'/(\d+)-', link)
            job_id = match.group(1) if match else ""
            if not job_id:
                match_slug = re.search(r'/SWIGGY/([^?#/]+)', link)
                job_id = match_slug.group(1) if match_slug else f"swiggy_{idx}"

            if not job_id or not title or str(job_id) in seen_ids:
                continue

            seen_ids.add(str(job_id))

            listings.append(JobListing(
                jobid=str(job_id),
                role_name=title,
                job_listing_link=link,
                location=location
            ))

        return listings

    def _parse_sr_postings(self, postings: list, seen_ids: Set[str], target_unit: str = "Technology") -> List[JobListing]:
        """Fallback parser for direct SmartRecruiters API response."""
        listings = []
        unit_lower = target_unit.lower()

        for idx, post in enumerate(postings):
            # Look for BusinessUnit in custom fields
            custom_fields = post.get("customField", [])
            bu = ""
            for cf in custom_fields:
                if cf.get("fieldLabel", "").lower() in ["businessunit", "business unit", "unit"]:
                    bu = cf.get("valueLabel", "")
                    break

            if bu.lower() != unit_lower:
                continue

            job_id = str(post.get("id", ""))
            title = str(post.get("name", "")).strip()
            
            loc_data = post.get("location", {})
            city = loc_data.get("city", "")
            region = loc_data.get("region", "")
            country = loc_data.get("country", "")
            loc_parts = [p for p in [city, region, country] if p]
            location = ", ".join(loc_parts) if loc_parts else "India"

            link = f"https://jobs.smartrecruiters.com/SWIGGY/{job_id}"
            if not job_id or not title or job_id in seen_ids:
                continue

            seen_ids.add(job_id)

            listings.append(JobListing(
                jobid=job_id,
                role_name=title,
                job_listing_link=link,
                location=location
            ))

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://careers.swiggy.in/explore-jobs?unit=Technology",
        }

        seen_ids = set()
        async with AsyncSession(impersonate="chrome124") as s:
            # 1. Primary endpoint: Swiggy static jobs.json
            api_url = "https://careers.swiggy.in/api/jobs.json"
            logger.info(f"Fetching Swiggy jobs from API: {api_url}")
            res = await s.get(api_url, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                jobs = data.get("jobs", [])
                parsed = self._parse_jobs(jobs, seen_ids, target_unit="Technology")
                if parsed:
                    return parsed

            # 2. Secondary endpoint: SmartRecruiters direct API
            sr_url = "https://api.smartrecruiters.com/v1/companies/SWIGGY/postings?limit=200"
            logger.info(f"Fetching Swiggy jobs from SmartRecruiters fallback: {sr_url}")
            res_sr = await s.get(sr_url, headers=headers, timeout=15)
            if res_sr.status_code == 200:
                data_sr = res_sr.json()
                postings = data_sr.get("content", [])
                parsed_sr = self._parse_sr_postings(postings, seen_ids, target_unit="Technology")
                if parsed_sr:
                    return parsed_sr

        return []

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Swiggy scrape via Playwright browser session fallback...")
        seen_ids = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()

                try:
                    await page.goto("https://careers.swiggy.in/explore-jobs?unit=Technology", wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    logger.warning(f"Playwright navigation warning on Swiggy explore jobs: {e}")

                data = await page.evaluate("""async () => {
                    try {
                        let res = await fetch("https://careers.swiggy.in/api/jobs.json");
                        if (!res.ok) return null;
                        return await res.json();
                    } catch(e) {
                        return null;
                    }
                }""")

                if data and isinstance(data, dict):
                    jobs = data.get("jobs", [])
                    return self._parse_jobs(jobs, seen_ids, target_unit="Technology")

            except Exception as pe:
                logger.error(f"Playwright fallback failed for Swiggy: {pe}")
            finally:
                await browser.close()

        return []

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Finished Swiggy Careers HTTP scrape. Found {len(listings)} Technology listings.")
                return listings
        except Exception as e:
            logger.warning(f"Swiggy HTTP scrape failed: {e}. Trying Playwright fallback...")

        try:
            listings = await self._scrape_playwright()
            logger.info(f"Finished Swiggy Careers Playwright fallback scrape. Found {len(listings)} Technology listings.")
            return listings
        except Exception as e:
            logger.error(f"Error in Swiggy portal Playwright fallback: {e}", exc_info=True)
            return []
