import logging
import asyncio
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PostmanPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "postman_careers"

    @property
    def portal_name(self) -> str:
        return "Postman Careers Portal"

    def _parse_api_jobs(
        self,
        jobs: list,
        seen_ids: Set[str],
        target_department: str = "engineering",
        target_locations: tuple = ("bangalore", "banglore", "bengaluru")
    ) -> List[JobListing]:
        listings = []
        dept_filter = target_department.lower()

        for j in jobs:
            dept = (j.get("department") or "").strip().lower()
            loc = (j.get("location") or "").strip().lower()

            if dept != dept_filter:
                continue

            if not any(loc_token in loc for loc_token in target_locations):
                continue

            job_id = str(j.get("id") or "").strip()
            title = (j.get("title") or "").strip()
            url = (j.get("url") or "").strip()
            location = (j.get("location") or "Bangalore, India").strip()

            if not job_id and url:
                id_match = re.search(r"_([A-Za-z0-9_-]+)$", url)
                if id_match:
                    job_id = id_match.group(1)
                else:
                    job_id = url.rstrip("/").split("/")[-1]

            if not job_id or not title or not url or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=url,
                    location=location
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        api_url = "https://www.postman.com/_mk-www-next/api-cache/careers-jobs.json"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.postman.com/company/careers/open-positions/",
            "Origin": "https://www.postman.com",
        }

        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(api_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"Postman careers API cache returned status {resp.status_code}")
                return []

            data = resp.json()
            jobs = data.get("jobs", []) if isinstance(data, dict) else []
            listings = self._parse_api_jobs(jobs, seen_ids)
            logger.info(f"Postman curl scraped {len(listings)} Engineering jobs in Bangalore from {len(jobs)} total jobs.")
            return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Postman careers scraping via Playwright...")
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
                page_url = "https://www.postman.com/company/careers/open-positions/"
                await page.goto(page_url, wait_until="domcontentloaded", timeout=40000)

                # Wait for open-positions section to load
                try:
                    await page.wait_for_selector("#open-positions", timeout=15000)
                except Exception:
                    await asyncio.sleep(2.0)

                # Interact with the UI filter controls
                try:
                    # Expand "Filter by Location" drawer if closed
                    loc_summary = await page.query_selector("details summary:has-text('Filter by Location')")
                    if loc_summary:
                        await loc_summary.click()
                        await asyncio.sleep(0.5)

                    # Select "Engineering" checkbox
                    eng_label = await page.query_selector("label:has-text('Engineering')")
                    if eng_label:
                        await eng_label.click()
                        await asyncio.sleep(0.4)

                    # Select "Bangalore, India" checkbox
                    bglr_label = await page.query_selector("label:has-text('Bangalore, India')")
                    if bglr_label:
                        await bglr_label.click()
                        await asyncio.sleep(1.0)
                except Exception as filter_err:
                    logger.warning(f"Error filtering Postman UI: {filter_err}")

                # Extract job links rendered on the page
                cards = await page.query_selector_all("a[href*='workdayjobs.com']")
                for card in cards:
                    href = (await card.get_attribute("href") or "").strip()
                    title = (await card.inner_text() or "").strip()

                    # Exclude non-job actions like 'Create an alert on Workday'
                    if not href or "/job/" not in href:
                        continue

                    id_match = re.search(r"_([A-Za-z0-9_-]+)$", href)
                    job_id = id_match.group(1) if id_match else href.rstrip("/").split("/")[-1]

                    if not job_id or not title or job_id in seen_ids:
                        continue

                    seen_ids.add(job_id)
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=href,
                            location="Bangalore, India"
                        )
                    )

                # Fallback to in-page evaluation if DOM links were not picked up
                if not listings:
                    logger.info("Attempting in-page evaluation for Postman jobs cache...")
                    api_data = await page.evaluate("""
                        async () => {
                            try {
                                const res = await fetch('/_mk-www-next/api-cache/careers-jobs.json');
                                return await res.json();
                            } catch (e) {
                                return null;
                            }
                        }
                    """)
                    if api_data and isinstance(api_data, dict):
                        raw_jobs = api_data.get("jobs", [])
                        listings = self._parse_api_jobs(raw_jobs, seen_ids)

                logger.info(f"Postman Playwright scraped {len(listings)} jobs.")
            except Exception as e:
                logger.error(f"Playwright scraping error for Postman: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. Fast direct API cache query
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Postman curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"Postman curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright browser fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Postman Playwright scraping also failed: {e}")
            return []
