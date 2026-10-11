import logging
import asyncio
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class GleanPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "glean_careers"

    @property
    def portal_name(self) -> str:
        return "Glean Careers Portal"

    def _parse_api_jobs(self, jobs: list, seen_ids: Set[str], location_filter: str = "bangalore") -> List[JobListing]:
        listings = []
        loc_filter_lower = location_filter.lower()

        for j in jobs:
            loc_obj = j.get("location") or {}
            loc_name = (loc_obj.get("name") or "").strip()
            
            # Filter specifically for Bangalore, India
            if loc_filter_lower not in loc_name.lower():
                continue

            job_id = str(j.get("id", "")).strip()
            title = (j.get("title") or "").strip()
            link = (j.get("absolute_url") or f"https://job-boards.greenhouse.io/gleanwork/jobs/{job_id}").strip()

            if not job_id or not title or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            listings.append(JobListing(
                jobid=job_id,
                role_name=title,
                job_listing_link=link,
                location=loc_name or "Bangalore, India"
            ))

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.glean.com/careers",
            "Origin": "https://www.glean.com",
        }

        api_url = "https://boards-api.greenhouse.io/v1/boards/gleanwork/jobs?content=true"
        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(api_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"Glean Greenhouse API returned status {resp.status_code}")
                return []

            data = resp.json()
            jobs = data.get("jobs", []) if isinstance(data, dict) else []
            listings = self._parse_api_jobs(jobs, seen_ids, location_filter="bangalore")
            logger.info(f"Glean curl API scraped {len(listings)} Bangalore, India jobs from {len(jobs)} total jobs.")
            return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Glean careers scraping via Playwright browser...")
        seen_ids: Set[str] = set()
        listings: List[JobListing] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            try:
                careers_url = "https://www.glean.com/careers#open-positions"
                await page.goto(careers_url, wait_until="domcontentloaded", timeout=40000)
                
                # Wait for Webflow job list ready class or fallback timeout
                try:
                    await page.wait_for_selector(".jobcontainer.is-list-ready", timeout=15000)
                except Exception:
                    await asyncio.sleep(3.0)

                # Select Bangalore, India in the Location dropdown
                try:
                    dropdowns = await page.query_selector_all(".blognew_select-filter_dropdown.is-career")
                    if len(dropdowns) >= 2:
                        loc_dropdown = dropdowns[1]
                        toggle = await loc_dropdown.query_selector(".w-dropdown-toggle")
                        if toggle:
                            await toggle.click()
                            await asyncio.sleep(0.5)
                            links = await loc_dropdown.query_selector_all(".w-dropdown-link, .is-dynamic-link")
                            for link in links:
                                text = (await link.inner_text()).strip()
                                if "bangalore" in text.lower():
                                    logger.info(f"Selecting location filter link: {text}")
                                    await link.click()
                                    break
                            await asyncio.sleep(1.0)
                except Exception as filter_err:
                    logger.warning(f"Error selecting location filter in dropdown: {filter_err}")

                # Collect cards from the active dept sections
                sections = await page.query_selector_all(".jobsection .jobs-dept_section.is-new")
                if not sections:
                    # In case section classes change slightly, check any visible job container cards
                    sections = await page.query_selector_all(".jobsection .jobs-dept_section")

                for sec in sections:
                    cards = await sec.query_selector_all(".jobs-container a.w-inline-block, .jobs-container a")
                    for card in cards:
                        href = await card.get_attribute("href") or ""
                        if not href or "job-boards.greenhouse.io" not in href:
                            continue

                        # Extract Greenhouse job ID from URL
                        id_match = re.search(r"/jobs/(\d+)", href)
                        job_id = id_match.group(1) if id_match else href.rstrip("/").split("/")[-1]

                        if not job_id or job_id in seen_ids:
                            continue

                        title_el = await card.query_selector(".careers-job-heading, .jobs-listing_title")
                        loc_el = await card.query_selector(".career-job-listing_location, .jobs-listing_location")

                        title = (await title_el.inner_text()).strip() if title_el else ""
                        loc_text = (await loc_el.inner_text()).strip() if loc_el else "Bangalore, India"

                        if not title:
                            continue

                        # Verify Bangalore is in location
                        if "bangalore" not in loc_text.lower():
                            continue

                        seen_ids.add(job_id)
                        listings.append(JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=href,
                            location=loc_text
                        ))

                # If no listings were found via DOM parsing, attempt client-side evaluate fetch
                if not listings:
                    logger.info("Attempting fallback fetch inside page context...")
                    api_data = await page.evaluate("""
                        async () => {
                            try {
                                const res = await fetch("https://boards-api.greenhouse.io/v1/boards/gleanwork/jobs?content=true");
                                return await res.json();
                            } catch(e) {
                                return null;
                            }
                        }
                    """)
                    if api_data and isinstance(api_data, dict):
                        raw_jobs = api_data.get("jobs", [])
                        listings = self._parse_api_jobs(raw_jobs, seen_ids, location_filter="bangalore")

                logger.info(f"Glean Playwright scraped {len(listings)} Bangalore, India jobs.")
            except Exception as e:
                logger.error(f"Playwright scraping error for Glean: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. High performance curl_cffi with Chrome fingerprinting
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Glean curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"Glean curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Glean Playwright scraping also failed: {e}")
            return []
