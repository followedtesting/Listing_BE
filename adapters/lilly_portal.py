import logging
import asyncio
import json
import ssl
import urllib.request
from typing import List, Set
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class LillyPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "lilly_careers"

    @property
    def portal_name(self) -> str:
        return "Eli Lilly Careers Portal"

    def _parse_jobs(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for j in jobs:
            jobid = j.get("jobId") or j.get("reqId") or j.get("jobSeqNo")
            title = j.get("title")

            if not jobid or not title:
                continue

            jobid_str = str(jobid).strip()
            title_str = str(title).strip()

            if jobid_str in seen_ids:
                continue

            seen_ids.add(jobid_str)

            # Extract location string
            location = j.get("cityStateCountry") or j.get("location")
            if not location:
                loc_parts = []
                if j.get("city"):
                    loc_parts.append(j.get("city"))
                if j.get("state"):
                    loc_parts.append(j.get("state"))
                if j.get("country"):
                    loc_parts.append(j.get("country"))
                location = ", ".join(loc_parts) if loc_parts else "India"

            job_listing_link = f"https://careers.lilly.com/us/en/job/{jobid_str}"

            listings.append(
                JobListing(
                    jobid=jobid_str,
                    role_name=title_str,
                    job_listing_link=job_listing_link,
                    location=location,
                )
            )
        return listings

    def _get_payload(self, offset: int, size: int) -> dict:
        return {
            "lang": "en_us",
            "deviceType": "desktop",
            "country": "us",
            "pageName": "search-results",
            "ddoKey": "refineSearch",
            "sortBy": "",
            "subsearch": "",
            "from": offset,
            "irs": False,
            "jobs": True,
            "counts": True,
            "all_fields": ["category", "country", "state", "city"],
            "size": size,
            "clearAll": False,
            "jdsource": "facets",
            "isSliderEnable": False,
            "pageId": "page1-e1e",
            "siteType": "external",
            "keywords": "",
            "global": True,
            "selected_fields": {
                "country": ["India"]
            },
            "locationData": {
                "placeId": "ChIJkbeSa_BfYzARphNChaFPjNc",
                "country": "India"
            }
        }

    async def _scrape_curl(self) -> List[JobListing]:
        url = "https://careers.lilly.com/widgets"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://careers.lilly.com",
            "Referer": "https://careers.lilly.com/us/en/search-results?keywords=&p=ChIJkbeSa_BfYzARphNChaFPjNc&location=India",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        size = 50
        max_pages = 20

        logger.info("Scraping Eli Lilly Careers Portal via Phenom People API (curl_cffi).")

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            for page in range(1, max_pages + 1):
                payload = self._get_payload(offset, size)
                res = await session.post(url, json=payload, timeout=25)
                if res.status_code != 200:
                    logger.error(f"Lilly API returned non-200 status code {res.status_code} on page {page}")
                    break

                try:
                    data = res.json()
                except Exception as e:
                    logger.error(f"Failed to parse JSON response from Lilly API: {e}")
                    break

                refine = data.get("refineSearch", {})
                total_hits = refine.get("totalHits", 0)
                jobs = refine.get("data", {}).get("jobs", [])

                if not jobs:
                    break

                page_listings = self._parse_jobs(jobs, seen_ids)
                listings.extend(page_listings)
                logger.info(f"Page {page}: Scraped {len(page_listings)} new job postings.")

                offset += size
                if offset >= total_hits:
                    break

        return listings

    async def _scrape_urllib_fallback(self) -> List[JobListing]:
        url = "https://careers.lilly.com/widgets"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://careers.lilly.com",
            "Referer": "https://careers.lilly.com/us/en/search-results?keywords=&p=ChIJkbeSa_BfYzARphNChaFPjNc&location=India",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        def fetch_all():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            offset = 0
            size = 50
            max_pages = 20

            while offset < 1000 and max_pages > 0:
                max_pages -= 1
                payload = self._get_payload(offset, size)
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
                try:
                    with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
                        if resp.status != 200:
                            break
                        data = json.loads(resp.read().decode("utf-8"))
                        refine = data.get("refineSearch", {})
                        total_hits = refine.get("totalHits", 0)
                        jobs = refine.get("data", {}).get("jobs", [])
                        if not jobs:
                            break
                        page_listings = self._parse_jobs(jobs, seen_ids)
                        listings.extend(page_listings)
                        offset += size
                        if offset >= total_hits:
                            break
                except Exception as ex:
                    logger.warning(f"urllib pagination error for Lilly: {ex}")
                    break
            return listings

        try:
            return await asyncio.to_thread(fetch_all)
        except Exception as e:
            logger.error(f"urllib fallback failed for Lilly: {e}")
            return []

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Finished Eli Lilly Careers scrape via curl_cffi. Found {len(listings)} listings.")
                return listings
        except Exception as e:
            logger.warning(f"curl_cffi scrape failed for Lilly: {e}. Trying urllib fallback...")

        listings = await self._scrape_urllib_fallback()
        logger.info(f"Finished Eli Lilly Careers scrape via fallback. Found {len(listings)} listings.")
        return listings
