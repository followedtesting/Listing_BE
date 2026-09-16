import json
import logging
import ssl
import urllib.request
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class BankOfAmericaPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "bank_of_america_careers"

    @property
    def portal_name(self) -> str:
        return "Bank of America Careers Portal"

    async def scrape(self) -> List[JobListing]:
        api_base_url = "https://careers.bankofamerica.com/services/jobssearchservlet"
        logger.info("Scraping Bank of America Careers Portal via direct REST servlet API...")

        listings: List[JobListing] = []
        seen_ids = set()
        start = 0
        rows = 50
        max_pages = 20

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            while max_pages > 0:
                max_pages -= 1
                api_url = (
                    f"{api_base_url}?filters=area=Technology"
                    f"&start={start}&rows={rows}&search=jobsByLocation&searchstring=India"
                )
                logger.info(f"Fetching Bank of America jobs at start={start}: {api_url}")

                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"Bank of America API returned HTTP {resp.status}. Stopping pagination."
                        )
                        break

                    res_json = json.loads(resp.read().decode("utf-8"))
                    total_matches = res_json.get("totalMatches", 0)
                    jobs = res_json.get("jobsList", [])

                    if not jobs:
                        break

                    new_on_page = 0
                    for j in jobs:
                        job_id = str(j.get("jobRequisitionId") or "").strip()
                        title = str(j.get("postingTitle") or "").strip()
                        jcr_url = str(j.get("jcrURL") or "").strip()

                        if not job_id or not title or job_id in seen_ids:
                            continue

                        seen_ids.add(job_id)
                        new_on_page += 1

                        if jcr_url.startswith("http"):
                            link = jcr_url
                        elif jcr_url.startswith("/"):
                            link = f"https://careers.bankofamerica.com{jcr_url}"
                        else:
                            link = f"https://careers.bankofamerica.com/{jcr_url}"

                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=link
                            )
                        )

                    logger.info(f"Fetched {new_on_page} new Bank of America jobs at start={start}.")

                    if len(jobs) < rows or start + len(jobs) >= total_matches:
                        break

                    start += rows

        except Exception as e:
            logger.error(f"Failed to scrape Bank of America Careers Portal: {e}", exc_info=True)
            raise

        logger.info(f"Finished Bank of America Careers scrape. Found total {len(listings)} listings.")
        return listings
