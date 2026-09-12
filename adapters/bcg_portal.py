import logging
import json
import ssl
import re
import urllib.request
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class BCGPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "bcg_careers"

    @property
    def portal_name(self) -> str:
        return "BCG Careers Portal"

    async def scrape(self) -> List[JobListing]:
        logger.info("Fetching BCG Careers via direct HTTP request & phApp.ddo JSON parsing...")

        listings: List[JobListing] = []
        seen_ids = set()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        offset = 0
        max_pages = 20

        try:
            while offset < 1000 and max_pages > 0:
                max_pages -= 1
                url = f"https://careers.bcg.com/global/en/search-results?category=Technology%20and%20Engineering&country=India&from={offset}&s=1"
                logger.info(f"Fetching BCG Careers at offset {offset}: {url}")

                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(f"BCG URL returned HTTP {resp.status}. Ending pagination.")
                        break
                    html_content = resp.read().decode("utf-8")

                match = re.search(r'phApp\.ddo\s*=\s*({.*?});\s*phApp', html_content, re.DOTALL)
                if not match:
                    logger.warning(f"Could not locate phApp.ddo JSON block in BCG response HTML at offset {offset}.")
                    break

                ddo_json = json.loads(match.group(1))
                eager = ddo_json.get("eagerLoadRefineSearch", {})
                jobs = eager.get("data", {}).get("jobs", [])
                total_hits = eager.get("totalHits", 0)

                if not jobs:
                    break

                new_on_page = 0
                for j in jobs:
                    job_id = str(j.get("reqId") or j.get("jobId") or "").strip()
                    title = str(j.get("title") or "").strip().replace("\n", " ")

                    if not job_id or not title or job_id in seen_ids:
                        continue

                    seen_ids.add(job_id)
                    new_on_page += 1

                    position_url = j.get("positionUrl") or j.get("applyUrl") or ""
                    if position_url and position_url.startswith("http"):
                        link = position_url
                    elif position_url:
                        link = f"https://careers.bcg.com{position_url if position_url.startswith('/') else '/' + position_url}"
                    else:
                        link = f"https://careers.bcg.com/global/en/job/{job_id}"

                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=link
                        )
                    )

                logger.info(f"Fetched {new_on_page} new BCG jobs at offset {offset} (total hits: {total_hits}).")

                if new_on_page == 0 or offset + len(jobs) >= total_hits:
                    break

                offset += len(jobs)

        except Exception as e:
            logger.error(f"Failed to scrape BCG Careers Portal: {e}", exc_info=True)
            raise

        logger.info(f"Finished BCG Careers scrape. Found total {len(listings)} listings.")
        return listings

