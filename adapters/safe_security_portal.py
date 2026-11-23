import logging
import asyncio
import json
import ssl
import urllib.request
from typing import List, Set
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SafeSecurityPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "safe_security_careers"

    @property
    def portal_name(self) -> str:
        return "Safe Security Careers Portal"

    def _format_location(self, loc: str) -> str:
        loc = (loc or "").strip()
        if not loc:
            return "Bengaluru, India"
        if "india" not in loc.lower():
            return f"{loc}, India"
        return loc

    def _parse_api_jobs(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings: List[JobListing] = []
        for j in jobs:
            job_id = str(j.get("id") or "").strip()
            title = (j.get("text") or "").strip()
            if not job_id or not title or job_id in seen_ids:
                continue

            cats = j.get("categories") or {}
            raw_loc = cats.get("location") or ""
            all_locs = cats.get("allLocations") or []

            # Check if Bengaluru or Bangalore is present
            matches_location = (
                "bengaluru" in raw_loc.lower()
                or "bangalore" in raw_loc.lower()
                or any("bengaluru" in l.lower() or "bangalore" in l.lower() for l in all_locs)
            )
            if not matches_location and raw_loc:
                continue

            location = self._format_location(raw_loc or "Bengaluru")
            link = (j.get("hostedUrl") or (j.get("urls") or {}).get("show") or f"https://jobs.lever.co/safe/{job_id}").strip()

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

    def _parse_html_jobs(self, html: str, seen_ids: Set[str]) -> List[JobListing]:
        listings: List[JobListing] = []
        soup = BeautifulSoup(html, "html.parser")
        postings = soup.find_all("div", class_="posting")

        for p in postings:
            title_el = p.find("h5", attrs={"data-qa": "posting-name"})
            link_el = p.find("a", class_="posting-title")
            loc_el = p.find("span", class_="sort-by-location")

            if not title_el or not link_el:
                continue

            title = title_el.get_text(strip=True)
            link = link_el.get("href", "").strip()
            raw_loc = loc_el.get_text(strip=True) if loc_el else "Bengaluru"

            matches_location = (
                "bengaluru" in raw_loc.lower()
                or "bangalore" in raw_loc.lower()
            )
            if not matches_location and raw_loc:
                continue

            # Extract job ID from link or data attribute
            job_id = p.get("data-qa-posting-id") or link.rstrip("/").split("/")[-1]
            if not job_id or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            location = self._format_location(raw_loc or "Bengaluru")

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
        url = "https://api.lever.co/v0/postings/safe?location=Bengaluru&mode=json"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        async with AsyncSession(impersonate="chrome124", timeout=30) as session:
            resp = await session.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return self._parse_api_jobs(data, set())
            else:
                logger.warning(f"Lever API returned status {resp.status_code} for safe")
        return []

    def _scrape_urllib_api(self) -> List[JobListing]:
        url = "https://api.lever.co/v0/postings/safe?location=Bengaluru&mode=json"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
            },
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                if isinstance(data, list):
                    return self._parse_api_jobs(data, set())
        return []

    def _scrape_urllib_html(self) -> List[JobListing]:
        url = "https://jobs.lever.co/safe?location=Bengaluru"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            if response.status == 200:
                html = response.read().decode("utf-8")
                return self._parse_html_jobs(html, set())
        return []

    async def scrape(self) -> List[JobListing]:
        logger.info("Fetching jobs from Safe Security Careers Portal...")

        # 1. Primary: curl_cffi on Lever API
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Safe Security via curl_cffi API")
                return listings
        except Exception as e:
            logger.warning(f"curl_cffi API scrape failed for Safe Security: {e}")

        # 2. Fallback: urllib on Lever API
        try:
            logger.info("Attempting Safe Security scrape via urllib API fallback...")
            loop = asyncio.get_running_loop()
            listings = await loop.run_in_executor(None, self._scrape_urllib_api)
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Safe Security via urllib API")
                return listings
        except Exception as e:
            logger.warning(f"urllib API fallback failed for Safe Security: {e}")

        # 3. Fallback: urllib on HTML page
        try:
            logger.info("Attempting Safe Security scrape via urllib HTML fallback...")
            loop = asyncio.get_running_loop()
            listings = await loop.run_in_executor(None, self._scrape_urllib_html)
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Safe Security via HTML fallback")
                return listings
        except Exception as e:
            logger.error(f"HTML fallback failed for Safe Security: {e}")

        return []
