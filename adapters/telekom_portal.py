import logging
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class TelekomPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "telekom_careers"

    @property
    def portal_name(self) -> str:
        return "Deutsche Telekom Careers Portal"

    async def scrape(self) -> List[JobListing]:
        logger.info("Scraping Deutsche Telekom Careers Portal.")
        
        base_url = "https://careers.telekom.com/api/jobs-proxy/search?experience_level=Working+student%3BStudent+internship%3BProfessional%3BJunior+entry%3BGraduate+program&location=India"
        
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

        listings: List[JobListing] = []
        seen_ids = set()
        page = 1

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            while True:
                target_url = f"{base_url}&page={page}"
                try:
                    res = await session.post(target_url, json={}, timeout=15)
                    if res.status_code != 200:
                        logger.warning(f"Deutsche Telekom API page {page} returned status code {res.status_code}")
                        break

                    data = res.json()
                    items = data.get("data", [])
                    if not items or not isinstance(items, list):
                        break

                    new_on_page = 0
                    for item in items:
                        job_id = str(item.get("requisition_id") or "").strip()
                        title = str(item.get("title") or item.get("job_title") or "").strip()
                        apply_url = str(item.get("apply_url") or "").strip()

                        if not job_id or not title:
                            continue

                        if job_id in seen_ids:
                            continue

                        seen_ids.add(job_id)
                        new_on_page += 1

                        job_link = apply_url if apply_url else f"https://careers.telekom.com/en/jobs/{job_id}"

                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=job_link
                            )
                        )

                    if new_on_page == 0 or len(items) < 20:
                        break

                    page += 1
                except Exception as e:
                    logger.error(f"Deutsche Telekom API page {page} scrape failed: {e}")
                    break

        logger.info(f"Finished Deutsche Telekom Careers scrape. Found total {len(listings)} listings.")
        return listings
