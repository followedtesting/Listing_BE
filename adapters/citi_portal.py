import logging
import re
import html
import ssl
import urllib.request
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class CitiPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "citi_careers"

    @property
    def portal_name(self) -> str:
        return "Citi Careers"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://jobs.citi.com/search-jobs"
        logger.info(f"Fetching Citi Careers via direct HTTP requests: {base_url}")

        listings: List[JobListing] = []
        seen_ids = set()
        india_keywords = ["india", "pune", "chennai", "mumbai", "bengaluru", "bangalore", "haryana", "gurgaon", "gurugram", "noida", "hyderabad", "delhi"]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        page_num = 1
        max_pages = 15

        try:
            while page_num <= max_pages:
                url = f"{base_url}?k=&l=India&orgIds=287&p={page_num}"
                logger.info(f"Fetching Citi Careers page {page_num}: {url}")

                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(f"Citi page {page_num} returned status {resp.status}. Ending pagination.")
                        break
                    page_html = resp.read().decode("utf-8")

                matches = re.findall(r'<a[^>]*href=\"([^\"]*/job/[^\"]*/(\d+))\"[^>]*>(.*?)</a>', page_html, re.DOTALL)
                if not matches:
                    break

                new_on_page = 0
                for href, jobid, title_raw in matches:
                    title = html.unescape(re.sub(r'<[^>]+>', '', title_raw)).strip()
                    if not jobid or not title or jobid in seen_ids:
                        continue

                    seen_ids.add(jobid)
                    new_on_page += 1

                    is_india = any(k in href.lower() or k in title.lower() for k in india_keywords)
                    if is_india:
                        full_link = href if href.startswith("http") else f"https://jobs.citi.com{href}"
                        listings.append(
                            JobListing(
                                jobid=jobid,
                                role_name=title,
                                job_listing_link=full_link
                            )
                        )

                if new_on_page == 0:
                    break

                page_num += 1

        except Exception as e:
            logger.error(f"Failed to scrape Citi Careers Portal: {e}", exc_info=True)
            raise

        logger.info(f"Finished Citi Careers scrape. Found total {len(listings)} listings.")
        return listings

