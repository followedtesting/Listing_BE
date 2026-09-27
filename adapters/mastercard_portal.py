import logging
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MastercardPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "mastercard_careers"

    @property
    def portal_name(self) -> str:
        return "Mastercard Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://careers.mastercard.com/widgets"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://careers.mastercard.com",
            "Referer": "https://careers.mastercard.com/us/en/search-results?s=1",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        size = 50
        max_pages = 20

        logger.info("Scraping Mastercard Careers Portal via Phenom People REST API.")

        import asyncio
        async def fetch_all():
            nonlocal offset
            async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
                for page in range(1, max_pages + 1):
                    payload = {
                        "lang": "en_us",
                        "deviceType": "desktop",
                        "country": "us",
                        "pageName": "search-results",
                        "ddoKey": "refineSearch",
                        "sortBy": "",
                        "subsearch": "",
                        "from": offset,
                        "irs": False,
                        "jobs": True,
                        "counts": True,
                        "all_fields": ["category", "country", "state", "city"],
                        "size": size,
                        "clearAll": False,
                        "jdsource": "facets",
                        "isSliderEnable": False,
                        "pageId": "page11-m5wUFh",
                        "siteType": "external",
                        "keywords": "",
                        "global": True,
                        "selected_fields": {
                            "country": ["India"],
                            "category": ["Engineering", "AI & Data"]
                        },
                        "locationData": {}
                    }

                    res = await session.post(url, json=payload)
                    if res.status_code != 200:
                        logger.error(f"Mastercard API returned non-200 status code {res.status_code} on page {page}")
                        break

                    try:
                        data = res.json()
                    except Exception as e:
                        logger.error(f"Failed to parse JSON response from Mastercard API: {e}")
                        break

                    refine = data.get("refineSearch", {})
                    total_hits = refine.get("totalHits", 0)
                    jobs = refine.get("data", {}).get("jobs", [])

                    if not jobs:
                        logger.info(f"No jobs returned on page {page}. Concluding scrape.")
                        break

                    page_listings_count = 0
                    for j in jobs:
                        jobid = j.get("jobId") or j.get("reqId")
                        title = j.get("title")

                        if not jobid or not title:
                            continue

                        jobid_str = str(jobid).strip()
                        title_str = str(title).strip()

                        if jobid_str in seen_ids:
                            continue

                        seen_ids.add(jobid_str)
                        page_listings_count += 1
                        
                        location_parts = []
                        if j.get("city"): location_parts.append(j.get("city"))
                        if j.get("state"): location_parts.append(j.get("state"))
                        if j.get("country"): location_parts.append(j.get("country"))
                        location = ", ".join(location_parts) if location_parts else "India"

                        job_listing_link = f"https://careers.mastercard.com/us/en/job/{jobid_str}"

                        listings.append(
                            JobListing(
                                jobid=jobid_str,
                                role_name=title_str,
                                job_listing_link=job_listing_link,
                                location=location
                            )
                        )

                    logger.info(f"Page {page}: Scraped {page_listings_count} new job postings.")

                    offset += size
                    if offset >= total_hits:
                        logger.info(f"Reached total hits ({total_hits}). Terminating pagination.")
                        break
                        
        await fetch_all()
        logger.info(f"Finished Mastercard Careers scrape. Found total {len(listings)} listings.")
        return listings
