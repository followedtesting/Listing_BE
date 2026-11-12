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

class AllstatePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "allstate_careers"

    @property
    def portal_name(self) -> str:
        return "Allstate Careers Portal"

    def _parse_jobs(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for j in jobs:
            # Check category: Technology
            cat = (j.get("primary_category") or "").strip()
            addtnl_cats = j.get("addtnl_categories") or []
            if isinstance(addtnl_cats, list):
                all_cats = [cat.lower()] + [str(c).lower() for c in addtnl_cats]
            else:
                all_cats = [cat.lower()]

            # Ensure Technology category
            if not any("technology" in c for c in all_cats):
                continue

            jobid = j.get("clientid") or j.get("ref") or j.get("id")
            title = j.get("title")

            if not jobid or not title:
                continue

            jobid_str = str(jobid).strip()
            title_str = str(title).strip()

            if jobid_str in seen_ids:
                continue

            seen_ids.add(jobid_str)

            # Location formatting
            city = j.get("primary_city") or ""
            country = j.get("primary_country") or ""
            if country.upper() in ["IN", "INDIA"]:
                country_str = "India"
            else:
                country_str = country or "India"

            if city:
                location = f"{city}, {country_str}"
            else:
                location = country_str

            # Construct job listing URL
            raw_url = j.get("url") or j.get("seo_url")
            if raw_url and raw_url.startswith("http"):
                job_listing_link = raw_url
            elif raw_url:
                job_listing_link = f"https://www.allstate.jobs{raw_url}"
            else:
                job_listing_link = f"https://www.allstate.jobs/job/{j.get('id')}"

            listings.append(
                JobListing(
                    jobid=jobid_str,
                    role_name=title_str,
                    job_listing_link=job_listing_link,
                    location=location,
                )
            )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        base_api_url = "https://jobsapi-internal.m-cloud.io/api/job"
        limit = 100
        offset = 1

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.allstate.jobs/job-search-results/?category[]=Technology&compliment[]=India",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        async with AsyncSession(impersonate="chrome124", timeout=30) as session:
            while True:
                params = [
                    ("organization", "2030"),
                    ("facet", "compliment:India"),
                    ("facet", "primary_category:Technology"),
                    ("limit", str(limit)),
                    ("offset", str(offset)),
                ]
                resp = await session.get(base_api_url, params=params, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Allstate API returned status {resp.status_code}")
                    break

                data = resp.json()
                total_hits = data.get("totalHits", 0)
                results = data.get("queryResult", [])

                if not results:
                    break

                batch = self._parse_jobs(results, seen_ids)
                listings.extend(batch)

                if len(listings) >= total_hits or len(results) < limit:
                    break

                offset += limit

        return listings

    def _scrape_urllib(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        base_api_url = "https://jobsapi-internal.m-cloud.io/api/job"
        limit = 100
        offset = 1

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        while True:
            params = [
                ("organization", "2030"),
                ("facet", "compliment:India"),
                ("facet", "primary_category:Technology"),
                ("limit", str(limit)),
                ("offset", str(offset)),
            ]
            query_str = urllib.parse.urlencode(params)
            url = f"{base_api_url}?{query_str}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.allstate.jobs/job-search-results/?category[]=Technology&compliment[]=India",
                },
            )
            with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
                if response.status != 200:
                    logger.warning(f"Allstate urllib fallback returned status {response.status}")
                    break
                raw_data = response.read().decode("utf-8")
                data = json.loads(raw_data)
                total_hits = data.get("totalHits", 0)
                results = data.get("queryResult", [])

                if not results:
                    break

                batch = self._parse_jobs(results, seen_ids)
                listings.extend(batch)

                if len(listings) >= total_hits or len(results) < limit:
                    break

                offset += limit

        return listings

    async def scrape(self) -> List[JobListing]:
        logger.info("Fetching jobs from Allstate Careers Portal...")
        # Try primary curl_cffi method
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Allstate Careers via curl_cffi")
                return listings
        except Exception as e:
            logger.warning(f"curl_cffi scraping failed for Allstate Careers: {e}")

        # Fallback to urllib
        try:
            logger.info("Attempting Allstate Careers scrape via urllib fallback...")
            loop = asyncio.get_running_loop()
            listings = await loop.run_in_executor(None, self._scrape_urllib)
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Allstate Careers via urllib")
                return listings
        except Exception as e:
            logger.error(f"urllib fallback scraping failed for Allstate Careers: {e}")

        return []
