import asyncio
import gc
import json
import logging
import re
import ssl
import urllib.request
from typing import List, Set, Dict, Any, Optional
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class SamsungPortalAdapter(BaseJobAdapter):
    """
    Adapter for Samsung Careers Portal (Workday).
    Target URL: https://sec.wd3.myworkdayjobs.com/en-US/Samsung_Careers?locations=0c974e8c1228010867596ab21b3c3469&locations=9903637af4ee10017a5e7c6741a30000&locations=189767dd6c9201b802603c83a5292c78&Location_Country=c4f78be1a8f14da0ab49ce1162348a5e&hiringCompany=189767dd6c9201554f3e5312a7290a85&jobFamilyGroup=189767dd6c9201e189e3eaa6db299dc7
    Filters:
      - Locations:
        - 0c974e8c1228010867596ab21b3c3469
        - 9903637af4ee10017a5e7c6741a30000
        - 189767dd6c9201b802603c83a5292c78
      - Location_Country: c4f78be1a8f14da0ab49ce1162348a5e (India)
      - hiringCompany: 189767dd6c9201554f3e5312a7290a85
      - jobFamilyGroup: 189767dd6c9201e189e3eaa6db299dc7
    """

    TARGET_URL = (
        "https://sec.wd3.myworkdayjobs.com/en-US/Samsung_Careers"
        "?locations=0c974e8c1228010867596ab21b3c3469"
        "&locations=9903637af4ee10017a5e7c6741a30000"
        "&locations=189767dd6c9201b802603c83a5292c78"
        "&Location_Country=c4f78be1a8f14da0ab49ce1162348a5e"
        "&hiringCompany=189767dd6c9201554f3e5312a7290a85"
        "&jobFamilyGroup=189767dd6c9201e189e3eaa6db299dc7"
    )
    API_URL = "https://sec.wd3.myworkdayjobs.com/wday/cxs/sec/Samsung_Careers/jobs"
    BASE_JOB_URL = "https://sec.wd3.myworkdayjobs.com/en-US/Samsung_Careers"

    APPLIED_FACETS = {
        "locations": [
            "0c974e8c1228010867596ab21b3c3469",
            "9903637af4ee10017a5e7c6741a30000",
            "189767dd6c9201b802603c83a5292c78",
        ],
        "Location_Country": [
            "c4f78be1a8f14da0ab49ce1162348a5e",
        ],
        "hiringCompany": [
            "189767dd6c9201554f3e5312a7290a85",
        ],
        "jobFamilyGroup": [
            "189767dd6c9201e189e3eaa6db299dc7",
        ],
    }

    @property
    def portal_id(self) -> str:
        return "samsung_careers"

    @property
    def portal_name(self) -> str:
        return "Samsung Careers Portal (Workday)"

    def _parse_job_postings(self, postings: list, seen_ids: Set[str]) -> List[JobListing]:
        """Parses Workday job postings into JobListing instances."""
        listings: List[JobListing] = []
        for job in postings:
            title = (job.get("title") or "").strip()
            ext_path = (job.get("externalPath") or "").strip()
            bullets = job.get("bulletFields") or []

            # Extract requisition / job ID
            job_id = None
            for b in bullets:
                if isinstance(b, str) and (
                    b.startswith("REQ") or b.startswith("JR") or b.startswith("R") or b.isdigit()
                ):
                    job_id = b.strip()
                    break

            # Fallback to suffix in externalPath (e.g. Software---Embedded_R55619-2 -> R55619-2)
            if not job_id and ext_path:
                id_match = re.search(r"_([A-Za-z0-9_-]+)$", ext_path)
                if id_match:
                    job_id = id_match.group(1).strip()
                else:
                    job_id = ext_path.rstrip("/").split("/")[-1]

            if not job_id or not title or job_id in seen_ids:
                continue

            # Format location
            loc_text = (job.get("locationsText") or "").strip()
            if not loc_text and bullets and isinstance(bullets[0], str):
                loc_text = bullets[0].strip()

            if not loc_text:
                loc_text = "India"
            elif "india" not in loc_text.lower():
                loc_text = f"{loc_text}, India"

            seen_ids.add(job_id)
            full_link = f"{self.BASE_JOB_URL}{ext_path}" if ext_path else self.TARGET_URL
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location=loc_text,
                )
            )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes Samsung Workday CXS API using curl_cffi."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.TARGET_URL,
            "Origin": "https://sec.wd3.myworkdayjobs.com",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        total_count = None

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                payload = {
                    "appliedFacets": self.APPLIED_FACETS,
                    "limit": limit,
                    "offset": offset,
                    "searchText": "",
                }

                resp = await session.post(self.API_URL, json=payload, headers=headers, timeout=25)
                if resp.status_code != 200:
                    logger.warning(f"Samsung Workday API returned HTTP {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                if total_count is None and "total" in data:
                    total_count = data.get("total")

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch)

                offset += len(postings)
                if total_count is not None and offset >= total_count:
                    break
                if len(postings) < limit:
                    break

        logger.info(f"Samsung curl scraped {len(listings)} jobs (total: {total_count}).")
        return listings

    def _scrape_urllib(self) -> List[JobListing]:
        """Synchronous urllib fallback with SSL-tolerant context."""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.TARGET_URL,
            "Origin": "https://sec.wd3.myworkdayjobs.com",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        total_count = None

        while True:
            payload = {
                "appliedFacets": self.APPLIED_FACETS,
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }
            req = urllib.request.Request(
                self.API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, context=ctx, timeout=25) as response:
                if response.status != 200:
                    logger.warning(f"Samsung urllib returned HTTP {response.status} at offset {offset}")
                    break

                raw_data = response.read().decode("utf-8")
                data = json.loads(raw_data)
                if total_count is None and "total" in data:
                    total_count = data.get("total")

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch)

                offset += len(postings)
                if total_count is not None and offset >= total_count:
                    break
                if len(postings) < limit:
                    break

        logger.info(f"Samsung urllib scraped {len(listings)} jobs (total: {total_count}).")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Low-RAM Playwright fallback executing fetch directly in browser context."""
        logger.info("Attempting Samsung scraping via Playwright fallback...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        total_count = None
        playwright_obj = None
        browser = None

        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                    "--disable-extensions",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            while True:
                payload = {
                    "appliedFacets": self.APPLIED_FACETS,
                    "limit": limit,
                    "offset": offset,
                    "searchText": "",
                }

                js_code = """
                async (args) => {
                    const response = await fetch(args.url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        },
                        body: JSON.stringify(args.payload)
                    });
                    if (!response.ok) return null;
                    return await response.json();
                }
                """
                data = await page.evaluate(js_code, {"url": self.API_URL, "payload": payload})
                if not data:
                    break

                if total_count is None and "total" in data:
                    total_count = data.get("total")

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                batch = self._parse_job_postings(postings, seen_ids)
                listings.extend(batch)

                offset += len(postings)
                if total_count is not None and offset >= total_count:
                    break
                if len(postings) < limit:
                    break

        except Exception as e:
            logger.error(f"Playwright fallback failed for Samsung: {e}", exc_info=True)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_obj:
                try:
                    await playwright_obj.stop()
                except Exception:
                    pass
            gc.collect()

        return listings

    async def scrape(self) -> List[JobListing]:
        logger.info("Fetching jobs from Samsung Careers Portal...")

        # 1. Primary: curl_cffi on Workday CXS API
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Samsung via curl_cffi")
                return listings
        except Exception as e:
            logger.warning(f"curl_cffi scraping failed for Samsung: {e}")

        # 2. Fallback: urllib on Workday CXS API
        try:
            logger.info("Attempting Samsung scrape via urllib fallback...")
            loop = asyncio.get_running_loop()
            listings = await loop.run_in_executor(None, self._scrape_urllib)
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Samsung via urllib")
                return listings
        except Exception as e:
            logger.warning(f"urllib fallback scraping failed for Samsung: {e}")

        # 3. Fallback: Playwright
        try:
            listings = await self._scrape_playwright()
            if listings:
                logger.info(f"Successfully scraped {len(listings)} jobs from Samsung via Playwright")
                return listings
        except Exception as e:
            logger.error(f"Playwright fallback scraping failed for Samsung: {e}")

        return []
