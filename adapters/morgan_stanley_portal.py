import logging
import json
import ssl
import urllib.request
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MorganStanleyPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "morgan_stanley_careers"

    @property
    def portal_name(self) -> str:
        return "Morgan Stanley Careers"

    async def scrape(self) -> List[JobListing]:
        base_api_url = "https://morganstanley.eightfold.ai/api/pcsx/search"
        logger.info("Scraping Morgan Stanley Careers via direct Eightfold REST API...")
        
        listings: List[JobListing] = []
        seen_ids = set()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        start = 0
        limit = 100
        max_pages = 10

        try:
            while len(listings) < 1000 and max_pages > 0:
                max_pages -= 1
                api_url = (
                    f"{base_api_url}?domain=morganstanley.com&start={start}&num={limit}"
                    f"&sort_by=timestamp&filter_businessarea=technology&filter_city=Mumbai&filter_city=Bengaluru"
                )
                logger.info(f"Fetching Morgan Stanley jobs at start={start}: {api_url}")

                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(f"Morgan Stanley API returned HTTP {resp.status}. Stopping API pagination.")
                        break

                    res_json = json.loads(resp.read().decode("utf-8"))
                    data = res_json.get("data", {})
                    positions = data.get("positions", [])

                    if not positions:
                        break

                    new_on_page = 0
                    for p in positions:
                        job_id = str(p.get("id") or p.get("position_id") or "").strip()
                        title = str(p.get("name") or p.get("title") or "").strip()

                        if not job_id or not title or job_id in seen_ids:
                            continue

                        seen_ids.add(job_id)
                        new_on_page += 1

                        pos_url = p.get("positionUrl") or f"/careers/job/{job_id}"
                        if pos_url.startswith("http"):
                            link = pos_url
                        elif pos_url.startswith("/"):
                            link = f"https://morganstanley.eightfold.ai{pos_url}"
                        else:
                            link = f"https://morganstanley.eightfold.ai/{pos_url}"

                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=link
                            )
                        )

                    logger.info(f"Fetched {new_on_page} new Morgan Stanley jobs at start={start}.")

                    if new_on_page == 0 or len(positions) < limit:
                        break

                    start += limit

        except Exception as e:
            logger.error(f"Failed to scrape Morgan Stanley Careers Portal: {e}", exc_info=True)
            raise

        logger.info(f"Finished Morgan Stanley Careers scrape. Found total {len(listings)} listings.")
        return listings
