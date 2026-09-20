import html
import json
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
        wp_api_url = "https://careersatagoda.com/wp-json/wp/v2/job"

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()

        logger.info("Scraping Agoda Careers Portal.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            # Strategy 1: Attempt primary vacancies HTML page
            try:
                res = await session.get(url, timeout=15)
                if res.status_code == 200:
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
            except Exception as e:
                logger.warning(f"Primary Agoda HTML scrape encountered issue: {e}")

            # Strategy 2: Fallback to WordPress REST API if 0 listings found
            if not listings:
                logger.info("Primary Agoda HTML returned 0 listings or failed. Falling back to WordPress REST API...")
                target_locs = ["gurugram", "gurgaon", "mumbai", "pune"]
                for page in range(1, 4):
                    try:
                        res_wp = await session.get(
                            wp_api_url,
                            params={"per_page": 100, "page": page},
                            headers={"Accept": "application/json", "User-Agent": headers["User-Agent"]},
                            timeout=15
                        )
                        if res_wp.status_code != 200:
                            break
                        items = res_wp.json()
                        if not items or not isinstance(items, list):
                            break

                        for item in items:
                            item_str = json.dumps(item).lower()
                            if any(loc in item_str for loc in target_locs):
                                title_raw = item.get("title", {}).get("rendered", "")
                                title_clean = html.unescape(title_raw).strip()
                                link = item.get("link", "")
                                slug = item.get("slug", "")

                                jobid_match = re.search(r'(\d+)', slug)
                                jobid_str = jobid_match.group(1) if jobid_match else str(item.get("id"))

                                if jobid_str not in seen_ids and title_clean:
                                    seen_ids.add(jobid_str)
                                    listings.append(
                                        JobListing(
                                            jobid=jobid_str,
                                            role_name=title_clean,
                                            job_listing_link=link
                                        )
                                    )
                    except Exception as e:
                        logger.error(f"Agoda WP REST API fallback page {page} failed: {e}")
                        break

        logger.info(f"Finished Agoda Careers scrape. Found total {len(listings)} listings.")
        return listings

