import logging
import json
import ssl
import urllib.request
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class DatabricksPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "databricks_careers"

    @property
    def portal_name(self) -> str:
        return "Databricks Careers"

    async def scrape(self) -> List[JobListing]:
        api_url = "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true"
        logger.info(f"Fetching Databricks Careers via direct Greenhouse API: {api_url}")

        listings: List[JobListing] = []
        seen_ids = set()
        india_cities = ["india", "bengaluru", "bangalore", "gurgaon", "gurugram", "noida", "hyderabad", "mumbai", "pune", "delhi"]

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                if resp.status != 200:
                    logger.error(f"Databricks Greenhouse API returned status {resp.status}")
                    return listings

                api_data = json.loads(resp.read().decode("utf-8"))

            if isinstance(api_data, dict) and "jobs" in api_data:
                jobs = api_data.get("jobs", [])
                logger.info(f"Retrieved {len(jobs)} total jobs from Databricks Greenhouse API.")

                for job in jobs:
                    job_id = str(job.get("id", "")).strip()
                    title = str(job.get("title", "")).strip()
                    loc_name = job.get("location", {}).get("name", "").strip()
                    depts = [d.get("name", "").strip() for d in job.get("departments", [])]

                    # Check India location
                    is_india = any(city in loc_name.lower() for city in india_cities)

                    # Engineering department rule: contains 'engineering' but NOT 'field engineering'
                    is_eng = any("engineering" in d.lower() and "field engineering" not in d.lower() for d in depts)

                    if is_india and is_eng and job_id and title and job_id not in seen_ids:
                        seen_ids.add(job_id)
                        job_link = f"https://www.databricks.com/company/careers/open-positions/job?gh_jid={job_id}"
                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=job_link
                            )
                        )

                logger.info(f"Databricks Greenhouse API matched {len(listings)} Engineering jobs in India.")

        except Exception as e:
            logger.error(f"Failed to scrape Databricks Careers Portal: {e}", exc_info=True)
            raise

        logger.info(f"Finished Databricks Careers scrape. Found total {len(listings)} listings.")
        return listings

