import logging
from typing import List
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PitneyBowesPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "pitney_bowes_careers"

    @property
    def portal_name(self) -> str:
        return "Pitney Bowes Careers Portal"

    async def scrape(self) -> List[JobListing]:
        api_url = "https://pitneybowes.wd1.myworkdayjobs.com/wday/cxs/pitneybowes/PBCareers/jobs"
        logger.info(f"Fetching Pitney Bowes Careers listings via Workday CXS API...")

        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 20
        total_jobs = None

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }

        async with AsyncSession(impersonate="chrome120") as session:
            try:
                while True:
                    payload = {
                        "appliedFacets": {
                            "locationRegionStateProvince": [
                                "c125e15453b44c968e77a8f2516b113f",
                                "a3c37012f51642f4a7b3dafc8ac37801"
                            ],
                            "locations": [
                                "a1a2d7f358311000cb5cc2c027230000",
                                "c5bdbe22169b01100cd0cc4fc9008913"
                            ]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }

                    resp = await session.post(api_url, json=payload, headers=headers, timeout=30)
                    if resp.status_code != 200:
                        logger.warning(f"Pitney Bowes Workday API returned status {resp.status_code}. Stopping pagination.")
                        break

                    res_json = resp.json()
                    if total_jobs is None:
                        total_jobs = res_json.get("total", 0)

                    postings = res_json.get("jobPostings", [])
                    logger.info(f"Retrieved {len(postings)} jobs from Pitney Bowes API (offset {offset}, total {total_jobs}).")

                    if not postings:
                        break

                    for job in postings:
                        title = (job.get("title") or "").strip()
                        external_path = (job.get("externalPath") or "").strip()
                        bullet_fields = job.get("bulletFields", [])
                        req_id = bullet_fields[0] if bullet_fields else ""

                        job_id = req_id if req_id else (external_path.split("/")[-1] if external_path else title)

                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            full_link = f"https://pitneybowes.wd1.myworkdayjobs.com/en-US/PBCareers{external_path}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )

                    if len(postings) < limit or offset + len(postings) >= (total_jobs or 0):
                        break

                    offset += limit

            except Exception as e:
                logger.error(f"Failed to scrape Pitney Bowes Careers Portal: {e}", exc_info=True)
                raise

        logger.info(f"Finished Pitney Bowes Careers scrape. Found total {len(listings)} listings.")
        return listings
