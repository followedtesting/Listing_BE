import logging
import asyncio
import re
from typing import List
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class DoorDashPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "doordash_careers"

    @property
    def portal_name(self) -> str:
        return "DoorDash Careers Portal"

    async def scrape(self) -> List[JobListing]:
        """
        Scrapes DoorDash Careers filtered by:
        Location: India
        Function: Software Engineering | Machine Learning Engineering
        """
        base_url = "https://careersatdoordash.com/job-search/?keyword=&location=India&function=Software%20Engineering%7CMachine%20Learning%20Engineering%7C"
        listings: List[JobListing] = []
        seen_ids = set()
        spage = 1

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            # We use curl_cffi to bypass Cloudflare protection on careersatdoordash.com
            async with AsyncSession(impersonate="chrome124", headers=headers) as s:
                while True:
                    url = f"{base_url}&spage={spage}"
                    logger.info(f"Fetching DoorDash Careers page {spage}: {url}")

                    resp = await s.get(url, timeout=25)
                    if resp.status_code != 200:
                        logger.warning(f"DoorDash page {spage} returned status {resp.status_code}")
                        break

                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select(".job-item")
                    if not cards:
                        break

                    new_on_page = 0
                    for card in cards:
                        title_elem = card.select_one(".title-container .value a")
                        if not title_elem:
                            continue

                        title = title_elem.get_text(strip=True)
                        link = title_elem.get("href", "").strip()

                        # Extract job id from link path
                        id_match = re.search(r"/(\d+)/?$", link)
                        job_id = id_match.group(1) if id_match else ""
                        if not job_id:
                            lbl = card.select_one(".title-container .label")
                            if lbl and "Job ID:" in lbl.text:
                                job_id = lbl.text.split("Job ID:")[-1].strip()

                        loc_elem = card.select_one(".location-container .value-secondary")
                        loc = loc_elem.get_text(strip=True) if loc_elem else "India"

                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=link,
                                    location=loc,
                                )
                            )
                            new_on_page += 1

                    logger.info(f"Page {spage}: retrieved {new_on_page} new job listings.")
                    if new_on_page == 0:
                        break

                    spage += 1

            logger.info(f"Finished DoorDash Careers scrape. Found total {len(listings)} listings.")
        except Exception as e:
            logger.error(f"Error scraping DoorDash portal: {e}", exc_info=True)

        return listings
