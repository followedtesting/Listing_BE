import logging
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MicronPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "micron_careers"

    @property
    def portal_name(self) -> str:
        return "Micron Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_page_url = "https://micron.eightfold.ai/careers?domain=micron.com&query=Software&start=0&location=India&sort_by=match&filter_include_remote=1"
        api_url = "https://micron.eightfold.ai/api/pcsx/search"
        
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": base_page_url,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()
        start = 0
        num = 10
        max_pages = 50

        logger.info("Scraping Micron Careers Portal via Eightfold AI REST API.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            # Initial session request to set cookies
            try:
                await session.get(base_page_url)
            except Exception as e:
                logger.warning(f"Initial page request to Micron Eightfold portal warning: {e}")

            for page in range(1, max_pages + 1):
                params = {
                    "domain": "micron.com",
                    "query": "Software",
                    "location": "India",
                    "start": start,
                    "num": num,
                    "sort_by": "match",
                    "filter_include_remote": 1
                }

                res = await session.get(api_url, params=params)
                if res.status_code != 200:
                    logger.error(f"Micron Eightfold API returned non-200 status code {res.status_code} on page {page}")
                    break

                try:
                    data = res.json()
                except Exception as e:
                    logger.error(f"Failed to parse JSON from Micron Eightfold API: {e}")
                    break

                data_obj = data.get("data", {})
                positions = data_obj.get("positions", [])

                if not positions:
                    logger.info(f"No positions returned on page {page}. Terminating scrape.")
                    break

                page_count = 0
                for p in positions:
                    jobid_raw = p.get("displayJobId") or p.get("atsJobId") or p.get("id")
                    title_raw = p.get("name")
                    pos_url = p.get("positionUrl")

                    if not jobid_raw or not title_raw:
                        continue

                    jobid_str = str(jobid_raw).strip()
                    title_str = str(title_raw).strip()

                    if jobid_str in seen_ids:
                        continue

                    seen_ids.add(jobid_str)
                    page_count += 1

                    if pos_url:
                        if pos_url.startswith("http"):
                            job_link = pos_url
                        else:
                            if not pos_url.startswith("/"):
                                pos_url = "/" + pos_url
                            job_link = f"https://micron.eightfold.ai{pos_url}"
                    else:
                        num_id = p.get("id")
                        job_link = f"https://micron.eightfold.ai/careers/job/{num_id}" if num_id else base_page_url

                    listings.append(
                        JobListing(
                            jobid=jobid_str,
                            role_name=title_str,
                            job_listing_link=job_link
                        )
                    )

                logger.info(f"Page {page}: Scraped {page_count} new job postings.")

                start += num
                results_meta = data_obj.get("resultsMetaData") or {}
                total_pos = results_meta.get("total_positions") or data_obj.get("count") or 0

                if start >= total_pos:
                    logger.info(f"Reached total positions ({total_pos}). Terminating pagination.")
                    break

        logger.info(f"Finished Micron Careers scrape. Found total {len(listings)} listings.")
        return listings
