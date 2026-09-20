import logging
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class OKXPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "okx_careers"

    @property
    def portal_name(self) -> str:
        return "OKX Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://boards-api.greenhouse.io/v1/boards/okx/departments/4004720003"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()

        logger.info("Scraping OKX Careers Portal via Greenhouse API.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            res = await session.get(url)
            if res.status_code != 200:
                logger.error(f"OKX Greenhouse API returned non-200 status code {res.status_code}")
                return listings

            try:
                data = res.json()
            except Exception as e:
                logger.error(f"Failed to parse JSON response from OKX Greenhouse API: {e}")
                return listings

            jobs = data.get("jobs", [])

            for j in jobs:
                jobid_raw = j.get("id")
                title_raw = j.get("title")

                if not jobid_raw or not title_raw:
                    continue

                offices = j.get("offices", [])
                office_ids = [str(o.get("id")) for o in offices]
                office_names = [o.get("name", "").lower() for o in offices]
                location_name = j.get("location", {}).get("name", "").lower()

                # Filter for Singapore office (office_id=4052439003)
                is_singapore = (
                    "4052439003" in office_ids
                    or any("singapore" in o_name for o_name in office_names)
                    or "singapore" in location_name
                )

                if not is_singapore:
                    continue

                jobid_str = str(jobid_raw).strip()
                title_str = str(title_raw).strip()

                if jobid_str in seen_ids:
                    continue

                seen_ids.add(jobid_str)

                job_link = j.get("absolute_url") or f"https://job-boards.greenhouse.io/okx/jobs/{jobid_str}"

                listings.append(
                    JobListing(
                        jobid=jobid_str,
                        role_name=title_str,
                        job_listing_link=job_link
                    )
                )

        logger.info(f"Finished OKX Careers scrape. Found total {len(listings)} listings.")
        return listings
