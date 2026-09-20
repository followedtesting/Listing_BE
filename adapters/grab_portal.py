import logging
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class GrabPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "grab_careers"

    @property
    def portal_name(self) -> str:
        return "Grab Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://www.grab.careers/en/jobs/?search=&team=Engineering&country=India&country=Singapore&pagesize=100"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()
        page = 1
        max_pages = 10

        logger.info("Scraping Grab Careers Portal via HTML parsing.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            while page <= max_pages:
                page_url = f"{base_url}&page={page}"
                res = await session.get(page_url)
                if res.status_code != 200:
                    logger.error(f"Grab Careers returned status code {res.status_code} on page {page}")
                    break

                soup = BeautifulSoup(res.text, "html.parser")
                job_links = soup.find_all("a", href=True)

                page_count = 0
                for a in job_links:
                    href = a.get("href", "").strip()
                    title = a.text.strip()

                    if "/en/jobs/" in href and not href.endswith("/en/jobs/") and "saved-jobs" not in href and "#" not in href:
                        parts = [p for p in href.split("/") if p]
                        # parts e.g. ['en', 'jobs', '744000149889977', 'ai-platform-architect-ai-transformation']
                        if len(parts) >= 3 and parts[2].isdigit():
                            jobid = parts[2]
                            if jobid in seen_ids or not title:
                                continue

                            seen_ids.add(jobid)
                            page_count += 1

                            full_link = f"https://www.grab.careers{href}" if href.startswith("/") else href

                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )

                logger.info(f"Page {page}: Scraped {page_count} new job postings.")

                if page_count == 0:
                    logger.info("No more job listings found. Terminating scrape.")
                    break

                page += 1

        logger.info(f"Finished Grab Careers scrape. Found total {len(listings)} listings.")
        return listings
