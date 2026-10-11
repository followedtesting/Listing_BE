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

class DevRevPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "devrev_careers"

    @property
    def portal_name(self) -> str:
        return "DevRev Careers Portal"

    async def scrape(self) -> List[JobListing]:
        """
        Scrapes DevRev careers filtered by:
        Location: Chennai, Bangalore, India Remote, Mumbai
        Department: Engineering - Applied AI Engineering, Engineering, Engineering - Community, Engineering Team
        """
        target_depts: Set[str] = {
            "Engineering - Applied AI Engineering",
            "Engineering",
            "Engineering - Community",
            "Engineering Team",
        }

        target_locations: List[str] = [
            "chennai",
            "bangalore",
            "bengaluru",
            "mumbai",
            "india remote",
            "remote, india",
            "india",
        ]

        listings: List[JobListing] = []
        seen_ids = set()

        # Method 1: Query Greenhouse public board API for devrev
        try:
            api_url = "https://boards-api.greenhouse.io/v1/boards/devrev/jobs?content=true"
            logger.info(f"Fetching DevRev jobs via Greenhouse API: {api_url}")

            def fetch_gh_data():
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                }
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
                return None

            data = await asyncio.to_thread(fetch_gh_data)
            if data and "jobs" in data:
                for j in data.get("jobs", []):
                    job_id = str(j.get("id", "")).strip()
                    title = str(j.get("title", "")).strip()
                    if not job_id or not title or job_id in seen_ids:
                        continue

                    # Filter by department
                    depts = [d.get("name", "").strip() for d in j.get("departments", [])]
                    dept_match = any(d in target_depts for d in depts)
                    if not dept_match:
                        continue

                    # Filter by location
                    loc_name = j.get("location", {}).get("name", "").strip()
                    offices = [o.get("name", "") + " " + o.get("location", "") for o in j.get("offices", [])]
                    all_loc_text = (loc_name + " " + " ".join(offices)).lower()

                    loc_match = any(tl in all_loc_text for tl in target_locations)
                    if not loc_match:
                        continue

                    job_link = j.get("absolute_url") or f"https://job-boards.greenhouse.io/devrev/jobs/{job_id}"
                    seen_ids.add(job_id)
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=job_link,
                            location=loc_name or "India",
                        )
                    )

                logger.info(f"Greenhouse API retrieved {len(listings)} matching jobs for DevRev.")
                if listings:
                    return listings
        except Exception as e:
            logger.warning(f"Error fetching DevRev jobs from Greenhouse API: {e}, falling back to website scrape...")

        # Method 2: Fallback to fetching directly from devrev.ai/careers using curl_cffi
        try:
            site_url = "https://devrev.ai/careers"
            logger.info(f"Fallback: Fetching DevRev careers directly from {site_url}")
            async with AsyncSession(impersonate="chrome124") as s:
                resp = await s.get(site_url)
                if resp.status_code == 200:
                    text = resp.text
                    idx = text.find("initialJobs")
                    if idx != -1:
                        bracket_start = text.find("[", idx)
                        depth = 0
                        bracket_end = -1
                        for i in range(bracket_start, len(text)):
                            if text[i] == "[":
                                depth += 1
                            elif text[i] == "]":
                                depth -= 1
                                if depth == 0:
                                    bracket_end = i
                                    break

                        raw_jobs = text[bracket_start:bracket_end + 1]
                        raw_unescaped = raw_jobs.replace('\\"', '"').replace('\\\\', '\\')
                        jobs = json.loads(raw_unescaped)

                        for j in jobs:
                            job_id = str(j.get("id", "")).strip()
                            title = str(j.get("title", "")).strip()
                            dept = str(j.get("department", "")).strip()
                            loc = str(j.get("location", "")).strip()
                            link = j.get("link") or f"https://job-boards.greenhouse.io/devrev/jobs/{job_id}"

                            if not job_id or not title or job_id in seen_ids:
                                continue

                            if dept in target_depts and any(tl in loc.lower() for tl in target_locations):
                                seen_ids.add(job_id)
                                listings.append(
                                    JobListing(
                                        jobid=job_id,
                                        role_name=title,
                                        job_listing_link=link,
                                        location=loc or "India",
                                    )
                                )
        except Exception as e:
            logger.error(f"Error in DevRev fallback website scrape: {e}")

        logger.info(f"Finished DevRev Careers scrape. Found total {len(listings)} listings.")
        return listings
