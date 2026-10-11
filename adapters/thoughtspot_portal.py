import logging
import asyncio
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ThoughtSpotPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "thoughtspot_careers"

    @property
    def portal_name(self) -> str:
        return "ThoughtSpot Careers Portal"

    def _parse_api_jobs(
        self,
        jobs: list,
        seen_ids: Set[str],
        target_department: str = "engineering"
    ) -> List[JobListing]:
        listings = []
        target_dept_lower = target_department.lower()

        for j in jobs:
            dept_obj = j.get("department") or {}
            dept_name = (dept_obj.get("name") or "").strip().lower()

            if dept_name != target_dept_lower:
                continue

            job_id = str(j.get("id") or "").strip()
            title = (j.get("name") or "").strip()
            url = (j.get("url") or f"https://ats.rippling.com/thoughtspot/jobs/{job_id}").strip()

            # Format location string
            locations = j.get("locations") or []
            loc_names = [l.get("name", "").strip() for l in locations if l.get("name")]
            loc_str = ", ".join(loc_names) if loc_names else "Bengaluru, India"

            if not job_id and url:
                job_id = url.rstrip("/").split("/")[-1]

            if not job_id or not title or not url or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=url,
                    location=loc_str
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        api_url = "https://www.thoughtspot.com/api/getCareersListing"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.thoughtspot.com/careers",
            "Origin": "https://www.thoughtspot.com",
        }

        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(api_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"ThoughtSpot careers API returned HTTP {resp.status_code}")
                return []

            data = resp.json()
            jobs = data.get("data", []) if isinstance(data, dict) else []
            listings = self._parse_api_jobs(jobs, seen_ids, target_department="engineering")
            logger.info(f"ThoughtSpot curl scraped {len(listings)} Engineering jobs from {len(jobs)} total jobs.")
            return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting ThoughtSpot careers scraping via Playwright...")
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
                page_url = "https://www.thoughtspot.com/careers#spotter"
                await page.goto(page_url, wait_until="domcontentloaded", timeout=40000)

                # Remove potential marketing popup overlays that could block page scripts
                try:
                    await page.evaluate("""() => {
                        const overlays = document.querySelectorAll('#report-modal-overlay, .vwo-popup, [id*="modal"]');
                        overlays.forEach(el => el.remove());
                    }""")
                except Exception:
                    pass

                # Fetch in-page data from API endpoint
                api_data = await page.evaluate("""
                    async () => {
                        try {
                            const res = await fetch("/api/getCareersListing");
                            return await res.json();
                        } catch (e) {
                            return null;
                        }
                    }
                """)

                if api_data and isinstance(api_data, dict):
                    raw_jobs = api_data.get("data", [])
                    listings = self._parse_api_jobs(raw_jobs, seen_ids, target_department="engineering")

                # If in-page evaluate failed, attempt DOM parsing
                if not listings:
                    try:
                        dept_btn = await page.query_selector("#spotter button:has-text('Choose job department')")
                        if dept_btn:
                            await dept_btn.click()
                            await asyncio.sleep(0.5)
                            eng_opt = await page.query_selector("#spotter li:has-text('Engineering'), #spotter [role='option']:has-text('Engineering')")
                            if eng_opt:
                                await eng_opt.click()
                                await asyncio.sleep(1.0)

                        cards = await page.query_selector_all("#spotter a[href*='ats.rippling.com']")
                        for card in cards:
                            href = (await card.get_attribute("href") or "").strip()
                            if not href:
                                continue
                            job_id = href.rstrip("/").split("/")[-1]
                            card_text = (await card.evaluate("el => el.closest('div') ? el.closest('div').innerText : el.innerText") or "").strip()
                            lines = [l.strip() for l in card_text.splitlines() if l.strip()]
                            title = lines[0] if lines else "Engineering Role"
                            loc = lines[1] if len(lines) > 1 else "Bengaluru, India"

                            if job_id and job_id not in seen_ids:
                                seen_ids.add(job_id)
                                listings.append(JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=href,
                                    location=loc
                                ))
                    except Exception as dom_err:
                        logger.warning(f"DOM fallback parsing for ThoughtSpot failed: {dom_err}")

                logger.info(f"ThoughtSpot Playwright scraped {len(listings)} jobs.")
            except Exception as e:
                logger.error(f"Playwright scraping error for ThoughtSpot: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. Fast direct API query
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("ThoughtSpot curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"ThoughtSpot curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"ThoughtSpot Playwright scraping also failed: {e}")
            return []
