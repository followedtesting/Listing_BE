import logging
import asyncio
import json
import ssl
import urllib.request
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class DoorDashPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "doordash_careers"

    @property
    def portal_name(self) -> str:
        return "DoorDash Careers Portal"

    async def _scrape_website(self) -> List[JobListing]:
        base_url = "https://careersatdoordash.com/job-search/?keyword=&location=India&function=Software%20Engineering%7CMachine%20Learning%20Engineering%7C"
        listings: List[JobListing] = []
        seen_ids = set()
        spage = 1

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with AsyncSession(impersonate="chrome124", headers=headers) as s:
                while True:
                    url = f"{base_url}&spage={spage}"
                    logger.info(f"Fetching DoorDash Careers page {spage}: {url}")

                    resp = await s.get(url, timeout=25)
                    if resp.status_code != 200:
                        logger.warning(f"DoorDash page {spage} returned status {resp.status_code}")
                        break

                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select(".job-item")
                    if not cards:
                        break

                    new_on_page = 0
                    for card in cards:
                        title_elem = card.select_one(".title-container .value a")
                        if not title_elem:
                            continue

                        title = title_elem.get_text(strip=True)
                        link = title_elem.get("href", "").strip()

                        # Extract job id from link path
                        id_match = re.search(r"/(\d+)/?$", link)
                        job_id = id_match.group(1) if id_match else ""
                        if not job_id:
                            lbl = card.select_one(".title-container .label")
                            if lbl and "Job ID:" in lbl.text:
                                job_id = lbl.text.split("Job ID:")[-1].strip()

                        loc_elem = card.select_one(".location-container .value-secondary")
                        loc = loc_elem.get_text(strip=True) if loc_elem else "India"

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
                            new_on_page += 1

                    if new_on_page == 0:
                        break
                    spage += 1
        except Exception as e:
            logger.warning(f"Website scrape error for DoorDash: {e}")

        return listings

    async def _scrape_greenhouse_fallback(self) -> List[JobListing]:
        """
        Fallback using DoorDash India's Greenhouse API board ('doordashindia').
        Bypasses Cloudflare blocking on Render/cloud hosting environments.
        """
        api_url = "https://boards-api.greenhouse.io/v1/boards/doordashindia/jobs?content=true"
        logger.info(f"Fetching DoorDash India jobs via Greenhouse board API: {api_url}")
        listings: List[JobListing] = []
        seen_ids = set()

        target_keywords = [
            "software",
            "data engine",
            "machine learning",
            "backend",
            "frontend",
            "fullstack",
            "platform",
            "infrastructure",
            "ai engine",
            "systems engine",
            "analytics engine",
        ]

        def fetch_gh():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8")).get("jobs", [])
            return []

        try:
            jobs = await asyncio.to_thread(fetch_gh)
            for j in jobs:
                job_id = str(j.get("id", "")).strip()
                title = str(j.get("title", "")).strip()
                if not job_id or not title or job_id in seen_ids:
                    continue

                depts = [d.get("name", "").lower() for d in j.get("departments", [])]
                is_eng = any(k in title.lower() for k in target_keywords) or any("engineering" in d for d in depts)
                if not is_eng:
                    continue

                loc_name = j.get("location", {}).get("name", "").strip() or "India"
                link = j.get("absolute_url") or f"https://job-boards.greenhouse.io/doordashindia/jobs/{job_id}"

                seen_ids.add(job_id)
                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=link,
                        location=loc_name,
                    )
                )
        except Exception as e:
            logger.error(f"Greenhouse fallback error for DoorDash India: {e}")

        return listings

    async def scrape(self) -> List[JobListing]:
        listings = await self._scrape_website()
        if not listings:
            logger.info("DoorDash website returned 0 listings (likely Cloudflare block on cloud IP). Trying Greenhouse API fallback...")
            listings = await self._scrape_greenhouse_fallback()

        logger.info(f"Finished DoorDash Careers scrape. Found total {len(listings)} listings.")
        return listings
