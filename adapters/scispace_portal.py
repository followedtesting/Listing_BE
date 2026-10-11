import logging
import asyncio
import json
import ssl
import urllib.request
from typing import List
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SciSpacePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "scispace_careers"

    @property
    def portal_name(self) -> str:
        return "SciSpace Careers Portal"

    async def scrape(self) -> List[JobListing]:
        """
        Scrapes SciSpace job listings from Instahyre using the internal search API:
        Company: SciSpace
        Job Category: /api/v1/job_category/1 (Software Engineering / Tech)
        """
        api_url = "https://www.instahyre.com/api/v1/job_search"
        listings: List[JobListing] = []
        seen_ids = set()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.instahyre.com/search-jobs?companies=SciSpace&company_size=0&isLandingPage=true&job_type=0&search=true&job_functions=%2Fapi%2Fv1%2Fjob_category%2F1",
        }

        offset = 0
        limit = 20

        try:
            async with AsyncSession(impersonate="chrome124", headers=headers) as s:
                while True:
                    params = {
                        "companies": "SciSpace",
                        "company_size": "0",
                        "isLandingPage": "true",
                        "job_type": "0",
                        "search": "true",
                        "job_categories": "1",
                        "offset": str(offset),
                        "limit": str(limit),
                    }

                    response = await s.get(api_url, params=params)
                    if response.status_code != 200:
                        logger.error(f"Instahyre API returned status {response.status_code}: {response.text[:200]}")
                        break

                    data = response.json()
                    objects = data.get("objects", [])
                    if not objects:
                        break

                    for job in objects:
                        job_id = str(job.get("id", "")).strip()
                        title = str(job.get("title", "")).strip()
                        locations = str(job.get("locations", "")).strip() or "India"
                        public_url = job.get("public_url") or f"https://www.instahyre.com/job-{job_id}/"

                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=public_url,
                                    location=locations,
                                )
                            )

                    meta = data.get("meta", {})
                    total_count = meta.get("total_count", 0)
                    offset += limit
                    if offset >= total_count:
                        break

            logger.info(f"Finished SciSpace Instahyre scrape. Found total {len(listings)} listings.")
        except Exception as e:
            logger.warning(f"Error in AsyncSession scrape for SciSpace: {e}, attempting fallback...")
            # Fallback using urllib via asyncio.to_thread
            try:
                def fetch_fallback():
                    fallback_listings = []
                    fb_seen = set()
                    fb_offset = 0
                    fb_limit = 20

                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                    while True:
                        url = f"{api_url}?companies=SciSpace&company_size=0&isLandingPage=true&job_type=0&search=true&job_categories=1&offset={fb_offset}&limit={fb_limit}"
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                            if resp.status != 200:
                                break
                            d = json.loads(resp.read().decode("utf-8"))
                            objs = d.get("objects", [])
                            if not objs:
                                break
                            for j in objs:
                                jid = str(j.get("id", "")).strip()
                                t = str(j.get("title", "")).strip()
                                loc = str(j.get("locations", "")).strip() or "India"
                                link = j.get("public_url") or f"https://www.instahyre.com/job-{jid}/"
                                if jid and t and jid not in fb_seen:
                                    fb_seen.add(jid)
                                    fallback_listings.append(
                                        JobListing(
                                            jobid=jid,
                                            role_name=t,
                                            job_listing_link=link,
                                            location=loc,
                                        )
                                    )
                            meta_fb = d.get("meta", {})
                            if fb_offset + fb_limit >= meta_fb.get("total_count", 0):
                                break
                            fb_offset += fb_limit
                    return fallback_listings

                listings = await asyncio.to_thread(fetch_fallback)
            except Exception as fb_err:
                logger.error(f"Fallback scrape also failed for SciSpace: {fb_err}", exc_info=True)

        return listings
