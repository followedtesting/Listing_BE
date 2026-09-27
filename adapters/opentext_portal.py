import json
import logging
import re
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class OpenTextPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "opentext_careers"

    @property
    def portal_name(self) -> str:
        return "OpenText Careers"

    async def scrape(self) -> List[JobListing]:
        logger.info("Scraping OpenText Careers Portal.")
        
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

        listings: List[JobListing] = []
        seen_ids = set()
        from_param = 0
        india_keywords = [
            "bangalore", "bengaluru", "pune", "hyderabad", "chennai", "gurgaon",
            "gurugram", "mumbai", "noida", "delhi", "karnataka", "maharashtra",
            "telangana", "tamil nadu", "haryana"
        ]

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            while True:
                url = f"https://careers.opentext.com/us/en/search-results?from={from_param}"
                try:
                    res = await session.get(url, timeout=15)
                    if res.status_code != 200:
                        logger.warning(f"OpenText page from={from_param} returned HTTP {res.status_code}")
                        break

                    match = re.search(r'phApp\.ddo\s*=\s*(\{.*?\});\s*phApp', res.text, re.DOTALL)
                    if not match:
                        logger.warning(f"OpenText page from={from_param} missing phApp.ddo structure.")
                        break

                    ddo = json.loads(match.group(1))
                    eager = ddo.get("eagerLoadRefineSearch", {})
                    total_hits = eager.get("totalHits", 0)
                    jobs = eager.get("data", {}).get("jobs", [])

                    if not jobs:
                        break

                    for j in jobs:
                        job_id = str(j.get("jobId") or j.get("reqId") or "").strip()
                        title = (j.get("title") or "").strip()

                        if not job_id or not title or job_id in seen_ids:
                            continue

                        country = str(j.get("country") or "").upper()
                        location = str(j.get("location") or j.get("cityStateCountry") or "").lower()

                        is_india = (country == "IND") or any(k in location for k in india_keywords) or ("india" in location)

                        if is_india:
                            seen_ids.add(job_id)
                            job_link = f"https://careers.opentext.com/us/en/job/{job_id}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=job_link
                                )
                            )

                    if from_param + len(jobs) >= total_hits or from_param >= 400:
                        break

                    from_param += 10
                except Exception as e:
                    logger.error(f"OpenText page from={from_param} scrape failed: {e}")
                    break

        logger.info(f"Finished OpenText Careers scrape. Found total {len(listings)} listings.")
        return listings
