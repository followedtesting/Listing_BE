import logging
import asyncio
import json
import ssl
import urllib.request
import urllib.parse
from typing import List, Set
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AonPortalAdapter(BaseJobAdapter):
    """
    Adapter for Aon Careers Portal (Jibe / iCIMS).
    Target URL: https://jobs.aon.com/jobs?location=India&stretch=10&stretchUnit=MILES&woe=12&regionCode=IN&page=1&categories=Software%20Engineering%7CTechnology%20(General)
    """

    TARGET_URL = (
        "https://jobs.aon.com/jobs"
        "?location=India&stretch=10&stretchUnit=MILES&woe=12&regionCode=IN&page=1"
        "&categories=Software%20Engineering%7CTechnology%20(General)"
    )
    API_URL = "https://jobs.aon.com/api/jobs"

    @property
    def portal_id(self) -> str:
        return "aon_careers"

    @property
    def portal_name(self) -> str:
        return "Aon Careers Portal"

    def _format_location(self, d: dict) -> str:
        loc = (d.get("short_location") or d.get("full_location") or "").strip()
        if not loc:
            city = (d.get("city") or "").strip()
            loc = f"{city}, India" if city else "India"
        elif "india" not in loc.lower():
            loc = f"{loc}, India"
        return loc

    def _parse_jobs(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for j in jobs:
            d = j.get("data", j)
            req_id = str(d.get("req_id") or d.get("slug") or "").strip()
            title = str(d.get("title") or "").strip()

            if not req_id or not title or req_id in seen_ids:
                continue

            slug = str(d.get("slug") or req_id).strip()
            job_link = f"https://jobs.aon.com/jobs/{slug}"
            location = self._format_location(d)

            seen_ids.add(req_id)
            listings.append(
                JobListing(
                    jobid=req_id,
                    role_name=title,
                    job_listing_link=job_link,
                    location=location,
                )
            )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        page = 1
        limit = 100
        total_count = None

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.TARGET_URL,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        async with AsyncSession(impersonate="chrome124", timeout=30) as session:
            while True:
                params = {
                    "location": "India",
                    "stretch": "10",
                    "stretchUnit": "MILES",
                    "woe": "12",
                    "regionCode": "IN",
                    "categories": "Software Engineering|Technology (General)",
                    "page": str(page),
                    "limit": str(limit),
                }
                resp = await session.get(self.API_URL, params=params, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Aon API returned status {resp.status_code} at page {page}")
                    break

                data = resp.json()
                if total_count is None and "totalCount" in data:
                    total_count = data.get("totalCount")

                raw_jobs = data.get("jobs", [])
                if not raw_jobs:
                    break

                batch = self._parse_jobs(raw_jobs, seen_ids)
                listings.extend(batch)

                if total_count is not None and len(seen_ids) >= total_count:
                    break
                if len(raw_jobs) < limit:
                    break

                page += 1

        logger.info(f"Aon curl scraped {len(listings)} jobs (total: {total_count}).")
        return listings

    def _scrape_urllib(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        page = 1
        limit = 100
        total_count = None

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        while True:
            params = [
                ("location", "India"),
                ("stretch", "10"),
                ("stretchUnit", "MILES"),
                ("woe", "12"),
                ("regionCode", "IN"),
                ("categories", "Software Engineering|Technology (General)"),
                ("page", str(page)),
                ("limit", str(limit)),
            ]
            query_str = urllib.parse.urlencode(params)
            url = f"{self.API_URL}?{query_str}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": self.TARGET_URL,
                },
            )
            with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
                if response.status != 200:
                    logger.warning(f"Aon urllib fallback returned status {response.status} at page {page}")
                    break

                raw_data = response.read().decode("utf-8")
                data = json.loads(raw_data)
                if total_count is None and "totalCount" in data:
                    total_count = data.get("totalCount")

                raw_jobs = data.get("jobs", [])
                if not raw_jobs:
                    break

                batch = self._parse_jobs(raw_jobs, seen_ids)
                listings.extend(batch)

                if total_count is not None and len(seen_ids) >= total_count:
                    break
                if len(raw_jobs) < limit:
                    break

                page += 1

        logger.info(f"Aon urllib scraped {len(listings)} jobs (total: {total_count}).")
        return listings

    async def scrape(self) -> List[JobListing]:
        logger.info("Fetching jobs from Aon Careers Portal...")

        # 1. Primary: curl_cffi on Jibe API
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Aon Careers via curl_cffi")
                return listings
        except Exception as e:
            logger.warning(f"curl_cffi scraping failed for Aon Careers: {e}")

        # 2. Fallback: urllib on Jibe API
        try:
            logger.info("Attempting Aon Careers scrape via urllib fallback...")
            loop = asyncio.get_running_loop()
            listings = await loop.run_in_executor(None, self._scrape_urllib)
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Aon Careers via urllib")
                return listings
        except Exception as e:
            logger.error(f"urllib fallback scraping failed for Aon Careers: {e}")

        return []
