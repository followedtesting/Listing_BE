import json
import logging
import ssl
import urllib.request
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SprinklrPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "sprinklr_careers"

    @property
    def portal_name(self) -> str:
        return "Sprinklr Careers (Workday)"

    async def scrape(self) -> List[JobListing]:
        api_url = "https://sprinklr.wd1.myworkdayjobs.com/wday/cxs/sprinklr/careers/jobs"
        logger.info(f"Scraping Sprinklr Careers via direct Workday REST API...")

        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 20
        total_jobs = None

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            while True:
                payload = {
                    "appliedFacets": {
                        "locationCountry": ["c4f78be1a8f14da0ab49ce1162348a5e"],
                        "jobFamilyGroup": ["c0a7c42494e701247f567aa7db035f64"]
                    },
                    "limit": limit,
                    "offset": offset,
                    "searchText": ""
                }

                req = urllib.request.Request(
                    api_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers
                )

                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(f"Sprinklr Workday API returned status {resp.status}. Stopping pagination.")
                        break

                    res_json = json.loads(resp.read().decode("utf-8"))
                    if total_jobs is None:
                        total_jobs = res_json.get("total", 0)

                    postings = res_json.get("jobPostings", [])
                    logger.info(f"Retrieved {len(postings)} jobs from Sprinklr Workday API (offset {offset}, total {total_jobs}).")

                    if not postings:
                        break

                    for job in postings:
                        title = (job.get("title") or "").strip()
                        external_path = (job.get("externalPath") or "").strip()
                        bullet_fields = job.get("bulletFields", [])
                        req_id = bullet_fields[0] if bullet_fields else ""

                        job_id = external_path.split("/")[-1] if external_path else (req_id or title)

                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            full_link = f"https://sprinklr.wd1.myworkdayjobs.com/en-US/careers{external_path}"
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
            logger.error(f"Failed to scrape Sprinklr Careers Portal: {e}", exc_info=True)
            raise

        logger.info(f"Finished Sprinklr Careers scrape. Found total {len(listings)} listings.")
        return listings
