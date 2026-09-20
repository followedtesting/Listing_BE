import json
import logging
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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids = set()

        logger.info("Scraping Revolut Careers Portal via __NEXT_DATA__ JSON extraction.")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            res = await session.get(url)
            if res.status_code != 200:
                logger.error(f"Revolut Careers returned non-200 status code {res.status_code}")
                return listings

            soup = BeautifulSoup(res.text, "html.parser")
            script_tag = soup.find("script", id="__NEXT_DATA__")

            if not script_tag or not script_tag.string:
                logger.error("Could not find __NEXT_DATA__ script tag in Revolut page.")
                return listings

            try:
                data = json.loads(script_tag.string)
            except Exception as e:
                logger.error(f"Failed to parse __NEXT_DATA__ JSON in Revolut page: {e}")
                return listings

            positions = data.get("props", {}).get("pageProps", {}).get("positions", [])

            for p in positions:
                jobid_raw = p.get("id")
                title_raw = p.get("text") or p.get("title")
                team_raw = p.get("team") or ""

                if not jobid_raw or not title_raw:
                    continue

                # Filter for Engineering team
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

        logger.info(f"Finished Revolut Careers scrape. Found total {len(listings)} listings.")
        return listings
