import logging
import asyncio
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NewRelicPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "newrelic_careers"

    @property
    def portal_name(self) -> str:
        return "New Relic Careers Portal"

    def _parse_greenhouse_jobs(self, raw_jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for j in raw_jobs:
            meta = {
                (m.get("name") or "").strip().lower(): (m.get("value") or "").strip()
                for m in j.get("metadata", [])
                if m.get("name")
            }
            aoi = meta.get("area of interest", "").lower()
            country = meta.get("country", "").lower()

            # Filter for areaOfInterest = Engineering
            if aoi != "engineering":
                continue

            loc_name = (j.get("location", {}).get("name") or "").strip()
            offices = [o.get("name") or "" for o in j.get("offices", [])]
            combined_loc_str = f"{loc_name} {' '.join(offices)}".lower()

            # Filter for India | Bangalore | Hyderabad
            is_target_location = (
                country == "india"
                or any(k in combined_loc_str for k in ["bangalore", "hyderabad", "bengaluru"])
                or bool(re.search(r"\bindia\b", combined_loc_str))
            )
            if not is_target_location:
                continue

            job_id = str(j.get("id") or "").strip()
            title = (j.get("title") or "").strip()
            link = (
                j.get("absolute_url")
                or f"https://job-boards.greenhouse.io/newrelic/jobs/{job_id}"
            ).strip()

            if not job_id or not title or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=link,
                    location=loc_name or "India"
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        api_url = "https://boards-api.greenhouse.io/v1/boards/newrelic/jobs?content=true"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://newrelic.com/careers?areaOfInterest=Engineering&location=India%7CBangalore%7CHyderabad",
            "Origin": "https://newrelic.com",
        }

        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(api_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"New Relic Greenhouse API returned HTTP {resp.status_code}")
                return []

            data = resp.json()
            raw_jobs = data.get("jobs", []) if isinstance(data, dict) else []
            listings = self._parse_greenhouse_jobs(raw_jobs, seen_ids)
            logger.info(f"New Relic curl scraped {len(listings)} Engineering jobs in India from {len(raw_jobs)} total jobs.")
            return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting New Relic careers scraping via Playwright...")
        target_url = "https://newrelic.com/careers?areaOfInterest=Engineering&location=India%7CBangalore%7CHyderabad"
        seen_ids: Set[str] = set()
        listings: List[JobListing] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)

                # Wait for rendered results
                try:
                    await page.wait_for_selector("a[href*='job-boards.greenhouse.io/newrelic/jobs/']", timeout=15000)
                except Exception:
                    await asyncio.sleep(2.0)

                # Extract links directly from DOM
                cards = await page.query_selector_all("a[href*='job-boards.greenhouse.io/newrelic/jobs/']")
                for card in cards:
                    href = (await card.get_attribute("href") or "").strip()
                    title = (await card.inner_text() or "").strip()

                    id_match = re.search(r"/jobs/(\d+)", href)
                    job_id = id_match.group(1) if id_match else href.rstrip("/").split("/")[-1]

                    if not job_id or not title or job_id in seen_ids:
                        continue

                    # Retrieve location from surrounding card if available
                    card_parent = await card.evaluate("el => el.closest('li') ? el.closest('li').innerText : (el.parentElement ? el.parentElement.innerText : '')")
                    loc = "India"
                    if "Bangalore" in card_parent:
                        loc = "Bangalore, India"
                    elif "Hyderabad" in card_parent:
                        loc = "Hyderabad, India"

                    seen_ids.add(job_id)
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=href,
                            location=loc
                        )
                    )

                # If DOM cards were not found, fallback to embedded drupalSettings
                if not listings:
                    logger.info("Falling back to drupalSettings in-page evaluate for New Relic...")
                    raw_jobs = await page.evaluate("""() => {
                        return window.drupalSettings && window.drupalSettings.jobSearchData ? window.drupalSettings.jobSearchData.jobs : null;
                    }""")
                    if raw_jobs and isinstance(raw_jobs, list):
                        listings = self._parse_greenhouse_jobs(raw_jobs, seen_ids)

                logger.info(f"New Relic Playwright scraped {len(listings)} jobs.")
            except Exception as e:
                logger.error(f"Playwright scraping error for New Relic: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. Fast direct API query
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("New Relic curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"New Relic curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"New Relic Playwright scraping also failed: {e}")
            return []
