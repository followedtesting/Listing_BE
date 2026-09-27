import logging
import re
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class FreshworksPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "freshworks_careers"

    @property
    def portal_name(self) -> str:
        return "Freshworks Careers Portal"

    async def scrape(self) -> List[JobListing]:
        logger.info("Scraping Freshworks Careers Portal.")

        urls = [
            "https://careers.smartrecruiters.com/Freshworks/pd",
            "https://careers.smartrecruiters.com/Freshworks",
        ]

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
            # Primary strategy: Scrape subsite HTML page
            for url in urls:
                try:
                    res = await session.get(url, timeout=15)
                    if res.status_code != 200:
                        logger.warning(f"Freshworks HTML page {url} returned status code {res.status_code}")
                        continue

                    soup = BeautifulSoup(res.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if "smartrecruiters.com/Freshworks/" in href:
                            match = re.search(r'/Freshworks/(\d+)', href)
                            if match:
                                job_id = match.group(1)
                                if job_id not in seen_ids:
                                    title_elem = a.find(["h3", "h4", "h5", "span"])
                                    title = title_elem.text.strip() if title_elem else a.text.strip()
                                    title = re.sub(r'Full-time|Part-time|Contractor|Internship', '', title, flags=re.I).strip()

                                    if job_id and title:
                                        seen_ids.add(job_id)
                                        clean_link = f"https://jobs.smartrecruiters.com/Freshworks/{job_id}"
                                        listings.append(
                                            JobListing(
                                                jobid=job_id,
                                                role_name=title,
                                                job_listing_link=clean_link
                                            )
                                        )

                    if listings:
                        logger.info(f"Successfully scraped Freshworks via HTML page {url}")
                        break
                except Exception as e:
                    logger.error(f"Error scraping Freshworks HTML page {url}: {e}")

            # Fallback to SmartRecruiters Public API if 0 listings found
            if not listings:
                logger.info("HTML scrape returned 0 listings. Falling back to SmartRecruiters Public API...")
                offset = 0
                limit = 100
                while True:
                    api_url = f"https://api.smartrecruiters.com/v1/companies/Freshworks/postings?offset={offset}&limit={limit}"
                    try:
                        res_api = await session.get(api_url, timeout=15)
                        if res_api.status_code != 200:
                            logger.warning(f"SmartRecruiters API returned status code {res_api.status_code}")
                            break

                        data = res_api.json()
                        items = data.get("content", [])
                        total_found = data.get("totalFound", 0)

                        if not items:
                            break

                        for item in items:
                            job_id = str(item.get("id") or "").strip()
                            title = str(item.get("name") or "").strip()
                            if job_id and title and job_id not in seen_ids:
                                seen_ids.add(job_id)
                                clean_link = f"https://jobs.smartrecruiters.com/Freshworks/{job_id}"
                                listings.append(
                                    JobListing(
                                        jobid=job_id,
                                        role_name=title,
                                        job_listing_link=clean_link
                                    )
                                )

                        if offset + len(items) >= total_found or len(items) < limit:
                            break
                        offset += limit
                    except Exception as e:
                        logger.error(f"SmartRecruiters API scrape failed at offset {offset}: {e}")
                        break

        logger.info(f"Finished Freshworks Careers scrape. Found total {len(listings)} listings.")
        return listings
