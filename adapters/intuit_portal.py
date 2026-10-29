import asyncio
import gc
import logging
import re
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class IntuitPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "intuit_careers"

    @property
    def portal_name(self) -> str:
        return "Intuit Careers"

    def _extract_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str], listings: List[JobListing]) -> int:
        cards = soup.select("#search-results list li, #search-results li, ul.search-results-list li, section#search-results li")
        tech_keywords = ["software", "engineer", "developer", "architect", "tech", "data engineer", "frontend", "backend", "fullstack", "full stack", "mobile", "ios", "android", "platform"]
        non_tech_keywords = ["product designer", "tax", "accountant", "facilitator", "recruiter", "program manager", "vendor partner", "business data analyst"]

        added = 0
        for li in cards:
            a = li.select_one("a[href*='/job/']")
            if not a:
                continue

            href = (a.get("href") or "").strip()
            loc_el = li.select_one(".job-location, .location")
            loc = loc_el.get_text(strip=True) if loc_el else ""

            # Check title from h2/h3 or a text
            h_tag = a.select_one("h2, h3")
            title = h_tag.get_text(strip=True) if h_tag else a.get_text(strip=True)
            title = title.replace("\n", " ").strip()

            match = re.search(r"/(\d+)$", href)
            job_id = match.group(1) if match else href

            if job_id and title and job_id not in seen_ids:
                seen_ids.add(job_id)

                is_india = any(k in href.lower() or k in loc.lower() or k in title.lower() for k in ["india", "bengaluru", "bangalore"])
                title_lower = title.lower()
                is_tech = any(k in title_lower for k in tech_keywords) and not any(nk in title_lower for nk in non_tech_keywords)

                if is_india and is_tech:
                    full_link = href if href.startswith("http") else f"https://jobs.intuit.com{href}"
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=full_link,
                            location=loc or "India",
                        )
                    )
                    added += 1

        return added

    async def _scrape_curl(self) -> List[JobListing]:
        base_url = "https://jobs.intuit.com/search-jobs/India/27595/2/1269750/0/0/100"
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        async with AsyncSession(impersonate="chrome120") as s:
            page_num = 1
            max_pages = 5
            while page_num <= max_pages:
                url = f"{base_url}/{page_num}"
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
        base_url = "https://jobs.intuit.com/search-jobs/India/27595/2/1269750/0/0/100"
        logger.info(f"Navigating to Intuit Careers via Playwright fallback: {base_url}/1")

        listings: List[JobListing] = []
        seen_ids = set()
        page_num = 1
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

            while True:
                url = f"{base_url}/{page_num}"
                res = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if not res or res.status != 200:
                    break

                await page.wait_for_timeout(1500)

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup

                if added == 0 or page_num >= 5:
                    break

                page_num += 1

        except Exception as e:
            logger.error(f"Playwright fallback failed for Intuit: {e}")
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
                logger.info(f"Intuit curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"Intuit curl scrape failed: {e}. Falling back to Playwright...")

        listings = await self._scrape_playwright()
        logger.info(f"Intuit Playwright scraped {len(listings)} jobs.")
        return listings
