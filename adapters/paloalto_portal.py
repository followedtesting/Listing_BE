import logging
import re
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PaloAltoPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "paloalto_careers"

    @property
    def portal_name(self) -> str:
        return "Palo Alto Networks Careers Portal"

    async def scrape(self) -> List[JobListing]:
        logger.info("Scraping Palo Alto Networks Careers Portal.")

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
        page = 1

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            while True:
                url = f"https://jobs.paloaltonetworks.com/en/search-jobs/India/47263/{page}"
                try:
                    res = await session.get(url, timeout=15)
                    if res.status_code != 200:
                        logger.warning(f"Palo Alto Networks page {page} returned status code {res.status_code}")
                        break

                    soup = BeautifulSoup(res.text, "html.parser")
                    job_links = soup.find_all("a", href=True, class_=re.compile("search-results-link|job", re.I))

                    if not job_links:
                        job_links = [a for a in soup.find_all("a", href=True) if "/job/" in a["href"]]

                    if not job_links:
                        break

                    new_on_page = 0
                    for a in job_links:
                        href = a["href"].strip()
                        if "/job/" not in href:
                            continue

                        match = re.search(r'-(\d+)$', href)
                        job_id = match.group(1) if match else a.get("data-job-id")

                        if not job_id or job_id in seen_ids:
                            continue

                        h2 = a.find(["h2", "h3", "h4"], class_=re.compile("title", re.I))
                        title = h2.text.strip() if h2 else ""
                        if not title:
                            headings = a.find_all(["h2", "h3", "h4"])
                            if headings:
                                title = headings[0].text.strip()
                        if not title:
                            title = a.text.strip().split("\n")[0]

                        loc_tag = a.find(class_=re.compile("location", re.I))
                        cat_tag = a.find(class_=re.compile("category", re.I))

                        location_text = loc_tag.text.strip() if loc_tag else ""
                        category_text = cat_tag.text.strip() if cat_tag else ""

                        is_product_eng = "product engineering" in category_text.lower() or "product engineering" in a.text.lower()
                        is_india = "india" in location_text.lower() or "india" in a.text.lower()

                        if is_product_eng and is_india and title:
                            seen_ids.add(job_id)
                            new_on_page += 1
                            full_link = href if href.startswith("http") else f"https://jobs.paloaltonetworks.com{href}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )

                    if new_on_page == 0:
                        break

                    page += 1
                except Exception as e:
                    logger.error(f"Palo Alto Networks page {page} scrape failed: {e}")
                    break

        logger.info(f"Finished Palo Alto Networks Careers scrape. Found total {len(listings)} listings.")
        return listings
