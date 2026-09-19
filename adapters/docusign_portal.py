import logging
from typing import List
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class DocuSignPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "docusign_careers"

    @property
    def portal_name(self) -> str:
        return "DocuSign Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://careers.docusign.com/api/jobs"
        logger.info(f"Fetching DocuSign Careers listings via REST API: {base_url}")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json"
        }

        listings: List[JobListing] = []
        seen_ids = set()
        page = 1
        max_pages = 30

        async with AsyncSession(impersonate="chrome120") as session:
            while page <= max_pages:
                params = {
                    "locations": "Bengaluru,Karnataka,India",
                    "categories": "Engineering",
                    "page": page,
                    "sortBy": "relevance",
                    "descending": "false",
                    "internal": ""
                }

                try:
                    resp = await session.get(base_url, params=params, headers=headers, timeout=30)
                    if resp.status_code != 200:
                        logger.warning(f"DocuSign API returned status {resp.status_code} on page {page}.")
                        break

                    data = resp.json()
                    raw_jobs = data.get("jobs", [])
                    if not raw_jobs:
                        logger.info(f"No more jobs on page {page}.")
                        break

                    new_on_page = 0
                    for item in raw_jobs:
                        job_data = item.get("data", {})
                        req_id = str(job_data.get("req_id") or job_data.get("slug") or "")
                        title = job_data.get("title", "").strip()

                        if not title:
                            continue

                        canonical = job_data.get("meta_data", {}).get("canonical_url")
                        if canonical:
                            link = canonical
                        elif req_id:
                            link = f"https://careers.docusign.com/careers-home/jobs/{req_id}"
                        else:
                            continue

                        jobid = req_id if req_id else link

                        if jobid and jobid not in seen_ids:
                            seen_ids.add(jobid)
                            new_on_page += 1
                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title,
                                    job_listing_link=link
                                )
                            )

                    total_count = data.get("totalCount", 0)
                    logger.info(f"DocuSign Page {page}: Fetched {len(raw_jobs)} raw jobs ({new_on_page} new). Total count: {total_count}")

                    if len(raw_jobs) < 10 or page * 10 >= total_count:
                        break

                    page += 1

                except Exception as page_err:
                    logger.error(f"Error fetching DocuSign API page {page}: {page_err}", exc_info=True)
                    break

        logger.info(f"Finished DocuSign Careers scrape. Found total {len(listings)} listings.")
        return listings
