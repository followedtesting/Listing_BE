import logging
import re
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class OktaPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "okta_careers"

    @property
    def portal_name(self) -> str:
        return "Okta Careers Portal"

    async def scrape(self) -> List[JobListing]:
        urls = [
            "https://www.okta.com/company/careers/job-listing/?department=All&location=5997",
            "https://www.okta.com/company/careers/job-listing/",
        ]

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

        logger.info("Scraping Okta Careers Portal.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            for url in urls:
                try:
                    res = await session.get(url, timeout=15)
                    if res.status_code != 200:
                        logger.warning(f"Okta Careers URL {url} returned status code {res.status_code}")
                        continue

                    soup = BeautifulSoup(res.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        title = a.text.strip()

                        if "/company/careers/" in href and href != "/company/careers/":
                            match = re.search(r'-(\d+)/?$', href)
                            if match and title:
                                job_id = match.group(1)
                                if job_id not in seen_ids:
                                    seen_ids.add(job_id)
                                    full_link = href if href.startswith("http") else f"https://www.okta.com{href}"
                                    listings.append(
                                        JobListing(
                                            jobid=job_id,
                                            role_name=title,
                                            job_listing_link=full_link
                                        )
                                    )

                    if listings:
                        logger.info(f"Successfully scraped Okta via {url}")
                        break
                except Exception as e:
                    logger.error(f"Okta scrape request to {url} failed: {e}")

        logger.info(f"Finished Okta Careers scrape. Found total {len(listings)} listings.")
        return listings
