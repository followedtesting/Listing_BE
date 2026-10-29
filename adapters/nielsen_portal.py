import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NielsenPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "nielsen_careers"

    @property
    def portal_name(self) -> str:
        return "Nielsen Careers (SmartRecruiters)"

    def _parse_anchors_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        anchors = soup.select("a[href*='jobs.smartrecruiters.com/TheNielsenCompany/']")
        for a in anchors:
            href = a.get("href")
            if not href:
                continue

            clean_url = href.split("?")[0].strip()
            parts = clean_url.rstrip("/").split("/")
            slug = parts[-1] if parts else ""
            job_id = slug.split("-")[0] if "-" in slug else slug

            if not job_id or job_id in seen_ids:
                continue

            h4 = a.select_one("h4")
            title = h4.get_text(strip=True) if h4 else a.get_text(strip=True)
            if not title:
                continue

            seen_ids.add(job_id)
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=clean_url,
                    location="India",
                )
            )
        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        target_url = "https://careers.smartrecruiters.com/TheNielsenCompany/technology-jobs"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        seen_ids: Set[str] = set()
        async with AsyncSession(impersonate="chrome124") as s:
            resp = await s.get(target_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"Nielsen page returned status {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            listings = self._parse_anchors_from_soup(soup, seen_ids)
            del soup

        logger.info(f"Nielsen curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Nielsen...")
        target_url = "https://careers.smartrecruiters.com/TheNielsenCompany/technology-jobs"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
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
                ]
            )
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.route(
                    "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                    lambda route: route.abort()
                )
                await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                listings = self._parse_anchors_from_soup(soup, seen_ids)
                del soup
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"Nielsen curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
