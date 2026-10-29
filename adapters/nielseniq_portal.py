import gc
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NielsenIQPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "nielseniq_careers"

    @property
    def portal_name(self) -> str:
        return "NielsenIQ Careers"

    def _parse_items(self, items: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        india_cities = ["pune", "vadodara", "chennai", "gurgaon", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "noida"]
        tech_keywords = ["software", "engineer", "developer", "architect", "data", "qa", "sre", "devops", "tech", "platform", "infrastructure", "backend", "frontend", "full stack"]

        for item in items:
            loc = item.get("location", {})
            country = (loc.get("country") or "").strip().lower()
            city = (loc.get("city") or "").strip().lower()
            full_loc = (loc.get("fullLocation") or "").strip().lower()

            is_india = country in ["in", "india"] or "india" in full_loc or any(c in city for c in india_cities)
            if not is_india:
                continue

            team_labels = set()
            dept = item.get("department", {})
            if dept.get("label"): team_labels.add(dept["label"].lower())

            fn = item.get("function", {})
            if fn.get("label"): team_labels.add(fn["label"].lower())

            custom_fields = item.get("customField", [])
            for cf in custom_fields:
                v_label = cf.get("valueLabel")
                if v_label:
                    team_labels.add(v_label.lower())

            title = (item.get("name") or "").strip()
            title_lower = title.lower()

            is_tech = any("technology" in t or "engineering" in t or "tech" in t for t in team_labels)
            if not is_tech:
                is_tech = any(k in title_lower for k in tech_keywords)

            if is_tech:
                job_id = str(item.get("id") or "").strip()
                ref_num = str(item.get("refNumber") or "").strip()
                ref_id = ref_num or job_id

                if ref_id and title and ref_id not in seen_ids:
                    seen_ids.add(ref_id)
                    full_link = f"https://jobs.smartrecruiters.com/NielsenIQ/{job_id}"
                    listings.append(
                        JobListing(
                            jobid=ref_id,
                            role_name=title,
                            job_listing_link=full_link,
                            location=loc.get("fullLocation") or "India",
                        )
                    )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 100

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        async with AsyncSession(impersonate="chrome124") as s:
            while True:
                api_url = f"https://api.smartrecruiters.com/v1/companies/NielsenIQ/postings?limit={limit}&offset={offset}"
                resp = await s.get(api_url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"NielsenIQ API returned {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                total = data.get("totalFound", 0)
                items = data.get("content", [])
                if not items:
                    break

                batch_listings = self._parse_items(items, seen_ids)
                listings.extend(batch_listings)

                if len(items) < limit or offset + len(items) >= total:
                    break

                offset += limit

        logger.info(f"NielsenIQ curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for NielsenIQ...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 100

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
                await page.goto("https://nielseniq.com/", wait_until="domcontentloaded", timeout=30000)

                while True:
                    api_url = f"https://api.smartrecruiters.com/v1/companies/NielsenIQ/postings?limit={limit}&offset={offset}"
                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}');
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)

                    if not isinstance(data, dict) or "error" in data:
                        break

                    total = data.get("totalFound", 0)
                    items = data.get("content", [])
                    if not items:
                        break

                    batch_listings = self._parse_items(items, seen_ids)
                    listings.extend(batch_listings)

                    if len(items) < limit or offset + len(items) >= total:
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
            logger.warning(f"NielsenIQ curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
