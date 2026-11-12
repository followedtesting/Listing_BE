import logging
import asyncio
import json
import ssl
import urllib.request
from typing import List, Set
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class TekionPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "tekion_careers"

    @property
    def portal_name(self) -> str:
        return "Tekion Careers Portal"

    def _parse_api_jobs(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        target_country = "india"
        target_cities = ["india", "bangalore", "bengaluru", "chennai", "hyderabad", "pune", "delhi", "mumbai", "noida", "gurgaon"]

        for j in jobs:
            if not j.get("isListed", True):
                continue

            job_id = str(j.get("id", "")).strip()
            title = (j.get("title") or "").strip()
            if not job_id or not title or job_id in seen_ids:
                continue

            # Check location
            addr = j.get("address") or {}
            postal = addr.get("postalAddress") or {}
            country = (postal.get("addressCountry") or "").strip().lower()
            loc_raw = (j.get("location") or "").strip()
            loc_lower = loc_raw.lower()

            is_india = (country == target_country) or any(city in loc_lower for city in target_cities)
            if not is_india:
                continue

            locality = postal.get("addressLocality")
            if locality:
                location = f"{locality}, India"
            elif loc_raw:
                location = loc_raw
            else:
                location = "India"

            # Prefer official Tekion job openings view, fallback to Ashby URL
            link = f"https://tekion.com/job-openings/job?id={job_id}"
            if not link:
                link = (j.get("jobUrl") or f"https://jobs.ashbyhq.com/Tekion/{job_id}").strip()

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

    async def _scrape_api(self) -> List[JobListing]:
        """
        Primary method: Fetch directly from Ashby public posting API for tekion board.
        """
        api_url = "https://api.ashbyhq.com/posting-api/job-board/tekion"
        logger.info(f"Fetching Tekion jobs from Ashby API: {api_url}")
        seen_ids = set()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }

        # Try with AsyncSession (curl_cffi)
        try:
            async with AsyncSession(impersonate="chrome124") as s:
                res = await s.get(api_url, headers=headers, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    jobs = data.get("jobs", [])
                    listings = self._parse_api_jobs(jobs, seen_ids)
                    if listings:
                        return listings
        except Exception as e:
            logger.warning(f"AsyncSession failed for Tekion Ashby API: {e}")

        # Fallback to urllib in thread
        def fetch_urllib():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                if resp.status == 200:
                    d = json.loads(resp.read().decode("utf-8"))
                    return d.get("jobs", [])
            return []

        try:
            jobs = await asyncio.to_thread(fetch_urllib)
            if jobs:
                return self._parse_api_jobs(jobs, seen_ids)
        except Exception as e:
            logger.warning(f"urllib failed for Tekion Ashby API: {e}")

        return []

    async def scrape(self) -> List[JobListing]:
        listings = await self._scrape_api()
        logger.info(f"Finished Tekion Careers scrape. Found total {len(listings)} listings.")
        return listings
