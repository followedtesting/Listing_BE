import asyncio
import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class UHGPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "uhg_careers"

    @property
    def portal_name(self) -> str:
        return "UnitedHealth Group Careers Portal"

    def _extract_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str], listings: List[JobListing]) -> int:
        links = soup.select("a[href*='/job/']")
        added = 0
        for link in links:
            href_clean = (link.get("href") or "").strip()
            title = link.get_text(strip=True).replace("\n", " ")

            if not href_clean or not title:
                continue

            parts = href_clean.split("/")
            jobid = parts[-1]
            if "?" in jobid:
                jobid = jobid.split("?")[0]

            if jobid and title and jobid not in seen_ids:
                seen_ids.add(jobid)
                added += 1

                if href_clean.startswith("http"):
                    job_listing_link = href_clean
                else:
                    if not href_clean.startswith("/"):
                        href_clean = "/" + href_clean
                    job_listing_link = f"https://careers.unitedhealthgroup.com{href_clean}"

                listings.append(
                    JobListing(
                        jobid=jobid.strip(),
                        role_name=title,
                        job_listing_link=job_listing_link,
                        location="India",
                    )
                )
        return added

    async def _scrape_curl(self) -> List[JobListing]:
        base_url = "https://careers.unitedhealthgroup.com/search-jobs?acm=ALL&alrpm=1269750&ascf=[%7B%22key%22:%22custom_fields.JobFunction%22,%22value%22:%22Software+Engineering%22%7D]"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        async with AsyncSession(impersonate="chrome120") as s:
            page_num = 1
            max_pages = 20
            while page_num <= max_pages:
                url = f"{base_url}&p={page_num}"
                resp = await s.get(url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup
                if added == 0:
                    break
                page_num += 1

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        base_url = "https://careers.unitedhealthgroup.com/search-jobs?acm=ALL&alrpm=1269750&ascf=[%7B%22key%22:%22custom_fields.JobFunction%22,%22value%22:%22Software+Engineering%22%7D]"
        logger.info("Attempting UHG Careers scraping via Playwright fallback...")

        listings: List[JobListing] = []
        seen_ids = set()
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
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort()
            )

            page_num = 1
            max_pages = 20

            while page_num <= max_pages:
                url = f"{base_url}&p={page_num}"
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2000)

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup

                if added == 0:
                    break

                page_num += 1

        except Exception as e:
            logger.error(f"Playwright fallback failed for UHG: {e}")
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
                logger.info(f"UHG curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"UHG curl scrape failed: {e}. Falling back to Playwright...")

        listings = await self._scrape_playwright()
        logger.info(f"UHG Playwright scraped {len(listings)} jobs.")
        return listings
