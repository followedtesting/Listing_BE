import json
import logging
import ssl
import urllib.request
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class EricssonPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "ericsson_careers"

    @property
    def portal_name(self) -> str:
        return "Ericsson Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_api_url = "https://jobs.ericsson.com/api/pcsx/search"
        logger.info("Scraping Ericsson Careers Portal via direct Eightfold REST API...")

        listings: List[JobListing] = []
        seen_ids = set()
        start = 0
        limit = 10
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
            while len(listings) < 1000 and max_pages > 0:
                max_pages -= 1
                api_url = (
                    f"{base_api_url}?domain=ericsson.com&query=&location=India&start={start}&num={limit}"
                    f"&sort_by=distance&filter_include_remote=1"
                    f"&filter_function=technology+%26+research&filter_function=product+development"
                )
                logger.info(f"Fetching Ericsson jobs at start={start}: {api_url}")

                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(f"Ericsson API returned HTTP {resp.status}. Stopping API pagination.")
                        break

                    res_json = json.loads(resp.read().decode("utf-8"))
                    data = res_json.get("data", {})
                    positions = data.get("positions", [])

                    if not positions:
                        break

                    new_on_page = 0
                    for p in positions:
                        job_id = str(p.get("id") or p.get("atsJobId") or p.get("displayJobId") or "").strip()
                        title = str(p.get("name") or p.get("title") or "").strip()

                        if not job_id or not title or job_id in seen_ids:
                            continue

                        seen_ids.add(job_id)
                        new_on_page += 1

                        pos_url = p.get("positionUrl") or f"/careers/job/{job_id}"
                        if pos_url.startswith("http"):
                            link = pos_url
                        elif pos_url.startswith("/"):
                            link = f"https://jobs.ericsson.com{pos_url}"
                        else:
                            link = f"https://jobs.ericsson.com/{pos_url}"

                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=link
                            )
                        )

                    logger.info(f"Fetched {new_on_page} new Ericsson jobs at start={start}.")

                    if new_on_page == 0 or len(positions) < limit:
                        break

                    start += limit

        except Exception as e:
            logger.error(f"Failed to scrape Ericsson Careers Portal: {e}", exc_info=True)
            raise

        logger.info(f"Finished Ericsson Careers scrape. Found total {len(listings)} listings.")
        return listings
