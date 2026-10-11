import logging
import asyncio
import json
import ssl
import urllib.request
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class KrakenPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "kraken_careers"

    @property
    def portal_name(self) -> str:
        return "Kraken Careers Portal"

    def _parse_api_jobs(self, jobs: list, seen_ids: Set[str], target_dept: str = "Engineering") -> List[JobListing]:
        listings = []
        target_lower = target_dept.lower()

        for j in jobs:
            dept = (j.get("department") or "").strip().lower()
            team = (j.get("team") or "").strip().lower()

            if dept != target_lower and team != target_lower:
                continue

            job_id = str(j.get("id", "")).strip()
            title = (j.get("title") or "").strip()
            link = (j.get("jobUrl") or f"https://jobs.ashbyhq.com/kraken.com/{job_id}").strip()

            # Location formatting
            addr = j.get("address", {}).get("postalAddress", {})
            locality = addr.get("addressLocality", "")
            country = addr.get("addressCountry", "")
            loc_str = j.get("location", "")

            if locality and country:
                location = f"{locality}, {country}"
            elif loc_str:
                location = loc_str
            else:
                location = "Remote"

            if not job_id or not title or job_id in seen_ids:
                continue

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
        Primary method: Fetch directly from Ashby public posting API for kraken.com.
        """
        api_url = "https://api.ashbyhq.com/posting-api/job-board/kraken.com"
        logger.info(f"Fetching Kraken jobs from Ashby API: {api_url}")
        seen_ids = set()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }

        # Try with AsyncSession (curl_cffi)
        try:
            async with AsyncSession(impersonate="chrome124") as s:
                res = await s.get(api_url, headers=headers, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    jobs = data.get("jobs", [])
                    listings = self._parse_api_jobs(jobs, seen_ids, target_dept="Engineering")
                    if listings:
                        return listings
        except Exception as e:
            logger.warning(f"AsyncSession failed for Kraken Ashby API: {e}")

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
                return self._parse_api_jobs(jobs, seen_ids, target_dept="Engineering")
        except Exception as e:
            logger.warning(f"urllib failed for Kraken Ashby API: {e}")

        return []

    async def _scrape_html_fallback(self) -> List[JobListing]:
        """
        Fallback method: Fetch the HTML page and parse window.__appData.
        """
        target_url = "https://jobs.ashbyhq.com/kraken.com?departmentId=5f67bd79-103b-4ac1-8d79-952b45ea47c9"
        target_dept_id = "5f67bd79-103b-4ac1-8d79-952b45ea47c9"
        logger.info(f"Fallback: Fetching Kraken careers from {target_url}")
        listings = []
        seen_ids = set()

        try:
            async with AsyncSession(impersonate="chrome124") as s:
                res = await s.get(target_url, timeout=20)
                if res.status_code == 200:
                    m = re.search(r"window\.__appData\s*=\s*({.*?});", res.text)
                    if m:
                        app_data = json.loads(m.group(1))
                        job_board = app_data.get("jobBoard", {})
                        teams = job_board.get("teams", [])

                        # Build team hierarchy under target department
                        child_team_ids = {target_dept_id}
                        changed = True
                        while changed:
                            changed = False
                            for t in teams:
                                if t.get("parentTeamId") in child_team_ids and t["id"] not in child_team_ids:
                                    child_team_ids.add(t["id"])
                                    changed = True

                        postings = job_board.get("jobPostings", [])
                        for p in postings:
                            if p.get("teamId") in child_team_ids:
                                job_id = str(p.get("id", "")).strip()
                                title = str(p.get("title", "")).strip()
                                loc = p.get("locationName") or "Remote"
                                link = f"https://jobs.ashbyhq.com/kraken.com/{job_id}"

                                if job_id and title and job_id not in seen_ids:
                                    seen_ids.add(job_id)
                                    listings.append(
                                        JobListing(
                                            jobid=job_id,
                                            role_name=title,
                                            job_listing_link=link,
                                            location=loc,
                                        )
                                    )
        except Exception as e:
            logger.error(f"Error in Kraken HTML fallback: {e}")

        return listings

    async def scrape(self) -> List[JobListing]:
        listings = await self._scrape_api()
        if listings:
            logger.info(f"Finished Kraken Careers scrape via API. Found {len(listings)} listings.")
            return listings

        logger.info("Ashby API returned 0 listings for Kraken, trying HTML fallback...")
        listings = await self._scrape_html_fallback()
        logger.info(f"Finished Kraken Careers scrape via fallback. Found {len(listings)} listings.")
        return listings
