import logging
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ShopeePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "shopee_careers"

    @property
    def portal_name(self) -> str:
        return "Shopee Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://ats.workatsea.com/ats/api/v1/user/job/list/"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://careers.shopee.sg",
            "Referer": "https://careers.shopee.sg/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 50
        max_pages = 20

        logger.info("Scraping Shopee Careers Portal via Workatsea ATS API.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            for page in range(1, max_pages + 1):
                params = {
                    "limit": limit,
                    "offset": offset,
                    "city_ids": 25,
                    "department_ids": 6
                }

                res = await session.get(url, params=params)
                if res.status_code != 200:
                    logger.error(f"Shopee API returned non-200 status code {res.status_code} on page {page}")
                    break

                try:
                    data = res.json().get("data", {})
                except Exception as e:
                    logger.error(f"Failed to parse JSON response from Shopee API: {e}")
                    break

                job_list = data.get("job_list", [])
                total_count = data.get("total_count", 0)

                if not job_list:
                    logger.info(f"No jobs returned on page {page}. Terminating scrape.")
                    break

                page_count = 0
                for j in job_list:
                    jobid_raw = j.get("id") or j.get("job_id")
                    title_raw = j.get("job_name")

                    if not jobid_raw or not title_raw:
                        continue

                    jobid_str = str(jobid_raw).strip()
                    title_str = str(title_raw).strip()

                    if jobid_str in seen_ids:
                        continue

                    seen_ids.add(jobid_str)
                    page_count += 1

                    job_link = f"https://careers.shopee.sg/job-detail/{jobid_str}"

                    listings.append(
                        JobListing(
                            jobid=jobid_str,
                            role_name=title_str,
                            job_listing_link=job_link
                        )
                    )

                logger.info(f"Page {page}: Scraped {page_count} new job postings.")

                offset += limit
                if offset >= total_count:
                    logger.info(f"Reached total count ({total_count}). Terminating pagination.")
                    break

        logger.info(f"Finished Shopee Careers scrape. Found total {len(listings)} listings.")
        return listings
