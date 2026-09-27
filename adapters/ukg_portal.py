import logging
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class UKGPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "ukg_careers"

    @property
    def portal_name(self) -> str:
        return "UKG Careers Portal"

    async def scrape(self) -> List[JobListing]:
        logger.info("Scraping UKG Careers Portal.")

        base_url = "https://apply.ukg.com/api/pcsx/search?domain=ukg.com&query=&location=India&filter_function=Software+%26+Product+Development"

        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

        listings: List[JobListing] = []
        seen_ids = set()
        start = 0

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            while True:
                api_url = f"{base_url}&start={start}"
                try:
                    res = await session.get(api_url, timeout=15)
                    if res.status_code != 200:
                        logger.warning(f"UKG API returned status code {res.status_code} at start={start}")
                        break

                    data = res.json()
                    data_dict = data.get("data", {})
                    positions = data_dict.get("positions", [])

                    if not positions or not isinstance(positions, list):
                        break

                    new_on_page = 0
                    for p in positions:
                        pos_id = str(p.get("id") or "").strip()
                        title = str(p.get("name") or "").strip()
                        pos_url = p.get("positionUrl") or f"/careers/job/{pos_id}"

                        if not pos_id or not title:
                            continue

                        if pos_id in seen_ids:
                            continue

                        seen_ids.add(pos_id)
                        new_on_page += 1

                        full_link = pos_url if pos_url.startswith("http") else f"https://apply.ukg.com{pos_url}"

                        listings.append(
                            JobListing(
                                jobid=pos_id,
                                role_name=title,
                                job_listing_link=full_link
                            )
                        )

                    if new_on_page == 0:
                        break

                    start += len(positions)
                except Exception as e:
                    logger.error(f"UKG API scrape failed at start={start}: {e}")
                    break

        logger.info(f"Finished UKG Careers scrape. Found total {len(listings)} listings.")
        return listings
