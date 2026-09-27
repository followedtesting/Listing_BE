import logging
import re
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SproutsPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "sprouts_careers"

    @property
    def portal_name(self) -> str:
        return "Sprouts.ai Careers Portal"

    async def scrape(self) -> List[JobListing]:
        logger.info("Scraping Sprouts.ai Careers Portal.")

        url = "https://sprouts.ai/careers"

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

        listings: List[JobListing] = []
        seen_ids = set()

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            try:
                res = await session.get(url, timeout=15)
                if res.status_code != 200:
                    logger.warning(f"Sprouts.ai page returned status code {res.status_code}")
                    return listings

                soup = BeautifulSoup(res.text, "html.parser")
                open_roles = [h for h in soup.find_all(["h1", "h2", "h3"]) if "open roles" in h.text.lower()]
                section = open_roles[0].find_parent("section") if open_roles else soup

                h3_list = section.find_all("h3")
                for h3 in h3_list:
                    title = h3.text.strip()
                    if not title or len(title) < 3:
                        continue

                    # Search parent hierarchy for application link
                    container = h3.parent
                    a_tag = None
                    for _ in range(6):
                        if container:
                            a_tag = container.find("a", href=True)
                            if a_tag:
                                break
                            container = container.parent

                    apply_link = a_tag["href"].strip() if a_tag else "https://sprouts.ai/careers"

                    # Generate slug for job ID
                    slug = re.sub(r'[^a-zA-Z0-9]+', '-', title.lower()).strip('-')
                    job_id = f"sprouts-{slug}"

                    if job_id not in seen_ids:
                        seen_ids.add(job_id)
                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=apply_link
                            )
                        )
            except Exception as e:
                logger.error(f"Sprouts.ai scrape encountered error: {e}")

        logger.info(f"Finished Sprouts.ai Careers scrape. Found total {len(listings)} listings.")
        return listings
