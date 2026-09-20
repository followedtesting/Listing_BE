import json
import logging
import re
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class RevolutPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "revolut_careers"

    @property
    def portal_name(self) -> str:
        return "Revolut Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://www.revolut.com/en-IN/careers/?team=Engineering"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()

        logger.info("Scraping Revolut Careers Portal.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            try:
                res = await session.get(url, timeout=20)
                if res.status_code != 200:
                    logger.error(f"Revolut Careers returned non-200 status code {res.status_code}")
                    return listings

                soup = BeautifulSoup(res.text, "html.parser")
                script_tag = soup.find("script", id="__NEXT_DATA__")

                if script_tag:
                    raw_text = script_tag.string or script_tag.text or (script_tag.contents[0] if script_tag.contents else "")
                    if raw_text:
                        try:
                            data = json.loads(raw_text)
                            positions = data.get("props", {}).get("pageProps", {}).get("positions", [])
                            for p in positions:
                                jobid_raw = p.get("id")
                                title_raw = p.get("text") or p.get("title")
                                team_raw = p.get("team") or ""

                                if not jobid_raw or not title_raw:
                                    continue

                                if "engineering" not in str(team_raw).lower():
                                    continue

                                jobid_str = str(jobid_raw).strip()
                                title_str = str(title_raw).strip()

                                if jobid_str in seen_ids:
                                    continue

                                seen_ids.add(jobid_str)
                                job_link = f"https://www.revolut.com/en-IN/careers/position/{jobid_str}/"

                                listings.append(
                                    JobListing(
                                        jobid=jobid_str,
                                        role_name=title_str,
                                        job_listing_link=job_link
                                    )
                                )
                        except Exception as e:
                            logger.warning(f"Error parsing Revolut __NEXT_DATA__ JSON: {e}")

                # Fallback to direct HTML links parsing if __NEXT_DATA__ yielded nothing
                if not listings:
                    logger.info("Parsing direct HTML position links for Revolut...")
                    for a in soup.find_all("a", href=True):
                        href = a.get("href", "").strip()
                        title = a.text.strip()
                        if "/careers/position/" in href:
                            match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', href)
                            if match:
                                jobid_str = match.group(1)
                                if jobid_str not in seen_ids and title:
                                    seen_ids.add(jobid_str)
                                    job_link = href if href.startswith("http") else f"https://www.revolut.com{href}"
                                    listings.append(
                                        JobListing(
                                            jobid=jobid_str,
                                            role_name=title,
                                            job_listing_link=job_link
                                        )
                                    )
            except Exception as e:
                logger.error(f"Revolut scrape request failed: {e}", exc_info=True)

        logger.info(f"Finished Revolut Careers scrape. Found total {len(listings)} listings.")
        return listings

