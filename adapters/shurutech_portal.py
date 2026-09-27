import logging
import re
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ShuruTechPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "shurutech_careers"

    @property
    def portal_name(self) -> str:
        return "ShuruTech Careers Portal"

    async def scrape(self) -> List[JobListing]:
        logger.info("Scraping ShuruTech Careers Portal.")

        headers = {
            "accept": "application/json, text/html, */*",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

        listings: List[JobListing] = []
        seen_ids = set()

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            # Strategy A: Query ShuruTech Careers API
            try:
                api_url = "https://shurutech.com/api/careers"
                res = await session.get(api_url, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    items = data.get("data", [])
                    if isinstance(items, list):
                        for item in items:
                            job_id = str(item.get("id") or "").strip()
                            title = str(item.get("posting_title") or item.get("job_opening_name") or "").strip()

                            if job_id and title and job_id not in seen_ids:
                                seen_ids.add(job_id)
                                clean_link = f"https://jobs.shurutech.com/jobs/Careers/{job_id}"
                                listings.append(
                                    JobListing(
                                        jobid=job_id,
                                        role_name=title,
                                        job_listing_link=clean_link
                                    )
                                )
                if listings:
                    logger.info(f"Successfully scraped ShuruTech via API. Found {len(listings)} listings.")
            except Exception as e:
                logger.error(f"Error scraping ShuruTech API: {e}")

            # Strategy B: Fallback to HTML scrape if API returned 0 listings
            if not listings:
                logger.info("API returned 0 listings. Falling back to ShuruTech HTML scrape...")
                try:
                    html_url = "https://shurutech.com/careers"
                    res_html = await session.get(html_url, timeout=15)
                    if res_html.status_code == 200:
                        soup = BeautifulSoup(res_html.text, "html.parser")
                        for a in soup.find_all("a", href=True):
                            href = a["href"].strip()
                            title = a.text.strip()
                            match = re.search(r'Careers/(\d+)', href) or re.search(r'job.*?(\d+)', href)
                            if match and title:
                                job_id = match.group(1)
                                if job_id not in seen_ids:
                                    seen_ids.add(job_id)
                                    clean_link = href if href.startswith("http") else f"https://shurutech.com{href}"
                                    listings.append(
                                        JobListing(
                                            jobid=job_id,
                                            role_name=title,
                                            job_listing_link=clean_link
                                        )
                                    )
                except Exception as e:
                    logger.error(f"Error scraping ShuruTech HTML page: {e}")

        logger.info(f"Finished ShuruTech Careers scrape. Found total {len(listings)} listings.")
        return listings
