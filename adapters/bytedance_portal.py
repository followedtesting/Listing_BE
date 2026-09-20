import logging
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ByteDancePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "bytedance_careers"

    @property
    def portal_name(self) -> str:
        return "ByteDance Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://joinbytedance.com",
            "Referer": "https://joinbytedance.com/",
            "Website-Path": "en",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 50
        max_pages = 30

        logger.info("Scraping ByteDance Careers Portal via REST API.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            for page in range(1, max_pages + 1):
                payload = {
                    "recruitment_id_list": [],
                    "job_category_id_list": ["6704215862603155720"],
                    "subject_id_list": [],
                    "location_code_list": ["CT_44", "CT_163"],
                    "keyword": "",
                    "limit": limit,
                    "offset": offset
                }

                res = await session.post(url, json=payload)
                if res.status_code != 200:
                    logger.error(f"ByteDance API returned non-200 status code {res.status_code} on page {page}")
                    break

                try:
                    data = res.json().get("data", {})
                except Exception as e:
                    logger.error(f"Failed to parse JSON response from ByteDance API: {e}")
                    break

                posts = data.get("job_post_list", [])
                total_count = data.get("count", 0)

                if not posts:
                    logger.info(f"No posts returned on page {page}. Terminating scrape.")
                    break

                page_count = 0
                for p in posts:
                    jobid_raw = p.get("id") or p.get("code")
                    title_raw = p.get("title")

                    if not jobid_raw or not title_raw:
                        continue

                    jobid_str = str(jobid_raw).strip()
                    title_str = str(title_raw).strip()

                    if jobid_str in seen_ids:
                        continue

                    seen_ids.add(jobid_str)
                    page_count += 1

                    job_link = f"https://joinbytedance.com/position/{jobid_str}/detail"

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

        logger.info(f"Finished ByteDance Careers scrape. Found total {len(listings)} listings.")
        return listings
