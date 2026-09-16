import logging
import json
import ssl
import urllib.request
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AdobePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "adobe_careers"

    @property
    def portal_name(self) -> str:
        return "Adobe Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://careers.adobe.com/widgets"
        logger.info("Scraping Adobe Careers via direct Phenom REST API...")
        
        listings: List[JobListing] = []
        seen_ids = set()
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/json"
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        offset = 0
        limit = 200  # Fetch up to 200 listings in a single atomic call to avoid Phenom offset pagination tie-breaking shifts
        max_pages = 5

        while len(listings) < 1000 and max_pages > 0:
            max_pages -= 1
            payload = {
                "lang": "en_us",
                "deviceType": "desktop",
                "country": "us",
                "pageName": "Engineering and Product jobs",
                "ddoKey": "refineSearch",
                "sortBy": "",
                "subsearch": "",
                "from": offset,
                "irs": False,
                "jobs": True,
                "counts": True,
                "all_fields": ["remote", "country", "state", "city", "experienceLevel", "category", "profession", "employmentType", "jobLevel"],
                "pageType": "category",
                "size": limit,
                "clearAll": False,
                "jdsource": "facets",
                "isSliderEnable": False,
                "pageId": "page62-ds",
                "siteType": "external",
                "keywords": "",
                "global": True,
                "selected_fields": {
                    "category": ["Engineering and Product"],
                    "country": ["India"]
                },
                "locationData": {}
            }

            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

            try:
                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(f"Adobe API returned HTTP {resp.status}. Stopping API pagination.")
                        break

                    res_json = json.loads(resp.read().decode("utf-8"))
                    refine = res_json.get("refineSearch", {})
                    total_hits = refine.get("totalHits", 0)
                    jobs = refine.get("data", {}).get("jobs", [])

                    if not jobs:
                        break

                    new_on_page = 0
                    for j in jobs:
                        job_id = str(j.get("reqId") or j.get("jobId") or "").strip()
                        title = str(j.get("title") or "").strip()

                        if not job_id or not title:
                            continue

                        if job_id in seen_ids:
                            continue

                        seen_ids.add(job_id)
                        new_on_page += 1

                        position_url = j.get("positionUrl") or j.get("applyUrl") or ""
                        if position_url and position_url.startswith("http"):
                            link = position_url
                        elif position_url:
                            link = f"https://careers.adobe.com{position_url}"
                        else:
                            link = f"https://careers.adobe.com/us/en/job/{job_id}"

                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=link
                            )
                        )

                    logger.info(f"Fetched {new_on_page} new Adobe jobs at offset {offset} (total hits: {total_hits}).")

                    if new_on_page == 0 or offset + len(jobs) >= total_hits:
                        break

                    offset += limit

            except Exception as e:
                logger.error(f"Failed during Adobe API request at offset {offset}: {e}", exc_info=True)
                break

        logger.info(f"Finished Adobe Careers scrape. Found total {len(listings)} listings.")
        return listings


