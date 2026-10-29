import asyncio
import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class InnovaccerPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "innovaccer_careers"

    @property
    def portal_name(self) -> str:
        return "Innovaccer Careers Portal"

    def _extract_from_html(self, html: str, seen_ids: Set[str], listings: List[JobListing]) -> int:
        soup = BeautifulSoup(html, "html.parser")
        links = soup.find_all("a", href=lambda h: h and "workable.com/j/" in h)
        added = 0
        for a in links:
            href_clean = (a.get("href") or "").strip()
            title = a.get_text(strip=True)
            parent = a.find_parent()
            p_text = parent.get_text(" ", strip=True).lower() if parent else ""

            # Filter: Department contains 'engineering and analytics', Location contains 'noida' or 'india'
            if "engineering and analytics" in p_text and ("noida" in p_text or "india" in p_text):
                jobid = href_clean.split("/")[-1]
                title_clean = title.strip().replace("\n", " ")
                if jobid and title_clean and len(title_clean) > 3 and jobid not in seen_ids:
                    seen_ids.add(jobid)
                    listings.append(
                        JobListing(
                            jobid=jobid.strip(),
                            role_name=title_clean,
                            job_listing_link=href_clean,
                            location="Noida, India",
                        )
                    )
                    added += 1
        del soup
        return added

    async def _scrape_curl(self) -> List[JobListing]:
        url = "https://innovaccer.com/careers/jobs"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        async with AsyncSession(impersonate="chrome120") as s:
            resp = await s.get(url, headers=headers, timeout=25)
            if resp.status_code == 200 and resp.text:
                self._extract_from_html(resp.text, seen_ids, listings)
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        url = "https://innovaccer.com/careers/jobs"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
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
                    "--js-flags=--max-old-space-size=128",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            # Abort heavy assets
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,mp4,webm}",
                lambda route: route.abort()
            )

            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)

            html = await page.content()
            self._extract_from_html(html, seen_ids, listings)

            # If not extracted from static HTML, do interactive fallback
            if not listings:
                try:
                    dept_dropdown = await page.query_selector("text='Department'")
                    if dept_dropdown:
                        await dept_dropdown.click()
                        await page.wait_for_timeout(1000)
                        dept_option = await page.query_selector("text='Engineering and analytics'")
                        if dept_option:
                            await dept_option.click()
                        await page.wait_for_timeout(2000)
                except Exception:
                    pass

                try:
                    loc_dropdown = await page.query_selector("text='Location'")
                    if loc_dropdown:
                        await loc_dropdown.click()
                        await page.wait_for_timeout(1000)
                        loc_option = await page.query_selector("text='India, Uttar Pradesh, Noida'")
                        if loc_option:
                            await loc_option.click()
                        await page.wait_for_timeout(2000)
                except Exception:
                    pass

                links = await page.query_selector_all("a")
                for link in links:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()
                    if href and title and "workable.com/j/" in href:
                        title_clean = title.strip().replace("\n", " ")
                        href_clean = href.strip()
                        jobid = href_clean.split("/")[-1]
                        if jobid and title_clean and len(title_clean) > 3 and jobid not in seen_ids:
                            seen_ids.add(jobid)
                            listings.append(
                                JobListing(
                                    jobid=jobid.strip(),
                                    role_name=title_clean,
                                    job_listing_link=href_clean,
                                    location="Noida, India",
                                )
                            )

        except Exception as e:
            logger.error(f"Playwright fallback failed for Innovaccer: {e}")
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
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Innovaccer curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"Innovaccer curl scrape failed: {e}. Falling back to Playwright...")

        listings = await self._scrape_playwright()
        logger.info(f"Innovaccer Playwright scraped {len(listings)} jobs.")
        return listings
