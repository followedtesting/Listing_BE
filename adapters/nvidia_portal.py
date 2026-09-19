import logging
from typing import List
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NvidiaPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "nvidia_careers"

    @property
    def portal_name(self) -> str:
        return "NVIDIA Careers Portal"

    async def scrape(self) -> List[JobListing]:
        api_url = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
        logger.info(f"Fetching NVIDIA Careers listings via Workday CXS API: {api_url}")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }

        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 20
        total_jobs = None

        async with AsyncSession(impersonate="chrome120") as session:
            try:
                while True:
                    payload = {
                        "appliedFacets": {
                            "locationHierarchy1": ["2fcb99c455831013ea52b82135ba3266"],
                            "jobFamilyGroup": ["0c40f6bd1d8f10ae43ffaefd46dc7e78"]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }

                    resp = await session.post(api_url, json=payload, headers=headers, timeout=30)
                    if resp.status_code != 200:
                        logger.warning(f"NVIDIA Workday API returned non-200 status code {resp.status_code} at offset {offset}.")
                        break

                    data = resp.json()
                    if total_jobs is None:
                        total_jobs = data.get("total", 0)

                    postings = data.get("jobPostings", [])
                    logger.info(f"Retrieved {len(postings)} job postings from NVIDIA Workday API (offset {offset}, total {total_jobs}).")

                    if not postings:
                        break

                    new_on_page = 0
                    for job in postings:
                        title = (job.get("title") or "").strip()
                        ext_path = (job.get("externalPath") or "").strip()
                        bullet_fields = job.get("bulletFields", [])
                        req_id = bullet_fields[0] if bullet_fields else ""

                        jobid = str(req_id).strip() if req_id else (ext_path.split("_")[-1] if "_" in ext_path else ext_path.split("/")[-1])

                        if ext_path.startswith("http"):
                            job_listing_link = ext_path
                        else:
                            job_listing_link = f"https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite{ext_path}"

                        if jobid and title and jobid not in seen_ids:
                            seen_ids.add(jobid)
                            new_on_page += 1
                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title,
                                    job_listing_link=job_listing_link
                                )
                            )

                    if len(postings) < limit or offset + len(postings) >= (total_jobs or 0):
                        break

                    offset += limit

            except Exception as e:
                logger.error(f"Failed to scrape NVIDIA Careers Portal: {e}", exc_info=True)
                raise

        logger.info(f"Finished NVIDIA Careers scrape. Found total {len(listings)} listings.")
        return listings
