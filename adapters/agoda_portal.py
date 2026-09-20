import logging
import re
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AgodaPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "agoda_careers"

    @property
    def portal_name(self) -> str:
        return "Agoda Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://careersatagoda.com/vacancies/?location%5B%5D=Gurugram&location%5B%5D=Mumbai&location%5B%5D=Pune&job_type%5B%5D=Entry+Level"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()

        logger.info("Scraping Agoda Careers Portal via HTML parsing.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            res = await session.get(url)
            if res.status_code != 200:
                logger.error(f"Agoda Careers returned non-200 status code {res.status_code}")
                return listings

            soup = BeautifulSoup(res.text, "html.parser")
            job_links = soup.find_all("a", href=True)

            for a in job_links:
                href = a.get("href", "").strip()
                title = a.text.strip()

                if "/job/" in href:
                    match = re.search(r'/job/(\d+)', href)
                    if match:
                        jobid_str = match.group(1)

                        if jobid_str in seen_ids or not title:
                            continue

                        seen_ids.add(jobid_str)

                        job_link = href if href.startswith("http") else f"https://careersatagoda.com{href}"

                        listings.append(
                            JobListing(
                                jobid=jobid_str,
                                role_name=title,
                                job_listing_link=job_link
                            )
                        )

        logger.info(f"Finished Agoda Careers scrape. Found total {len(listings)} listings.")
        return listings
