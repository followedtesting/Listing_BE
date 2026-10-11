import asyncio
import logging
import math
import re
from typing import List, Set, Optional
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SopraSteriaPortalAdapter(BaseJobAdapter):
    """
    Adapter for Sopra Steria Careers Portal (Attrax platform).
    Target URL: https://careers.soprasteria.in/jobs?options=211&page=1
    Options=211 specifies Department: Engineering, Development, Applications.
    """

    BASE_URL = "https://careers.soprasteria.in/jobs?options=211"

    @property
    def portal_id(self) -> str:
        return "soprasteria_careers"

    @property
    def portal_name(self) -> str:
        return "Sopra Steria Careers Portal"

    def _extract_listings_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str]) -> List[JobListing]:
        """
        Extracts JobListing objects from the parsed page HTML.
        """
        listings: List[JobListing] = []
        tiles = soup.select(".attrax-vacancy-tile, .attrax-list-widget__item")

        for tile in tiles:
            # 1. Job ID
            job_id = tile.get("data-jobid")
            if not job_id:
                link_tag = tile.select_one("a[href*='jid-']")
                if link_tag and link_tag.get("href"):
                    m = re.search(r"jid-(\d+)", link_tag.get("href"))
                    if m:
                        job_id = m.group(1)

            if not job_id:
                continue

            job_id = str(job_id).strip()
            if job_id in seen_ids:
                continue

            # 2. Title & Link
            title_tag = tile.select_one(".attrax-vacancy-tile__title, a[href*='jid-']")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            if not title:
                continue

            href = (title_tag.get("href") or "").strip()
            if href.startswith("http"):
                full_link = href
            else:
                full_link = f"https://careers.soprasteria.in{href}"

            # 3. Location
            loc_tag = tile.select_one(
                ".attrax-vacancy-tile__location-freetext .attrax-vacancy-tile__item-value, "
                ".attrax-vacancy-tile__location-freetext, "
                ".attrax-vacancy-tile__location .attrax-vacancy-tile__item-value"
            )
            location = "India"
            if loc_tag:
                loc_text = loc_tag.get_text(strip=True)
                # Clean up if the label text was captured
                loc_text = re.sub(r"^Location\s*", "", loc_text, flags=re.I).strip()
                if loc_text:
                    location = loc_text

            seen_ids.add(job_id)
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location=location,
                )
            )

        return listings

    def _parse_total_results(self, soup: BeautifulSoup) -> Optional[int]:
        """
        Extract total results count from the Attrax pagination element if present.
        """
        total_el = soup.select_one(".attrax-pagination__total-results, .search-results-count")
        if total_el:
            text = total_el.get_text(strip=True)
            m = re.search(r"(\d+)\s+result", text, re.I)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
        return None

    async def _scrape_curl(self) -> List[JobListing]:
        """
        Scrapes Sopra Steria job listings across all pages using curl_cffi.
        """
        seen_ids: Set[str] = set()
        listings: List[JobListing] = []

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://careers.soprasteria.in/",
        }

        async with AsyncSession(impersonate="chrome124") as session:
            # Fetch Page 1 first
            first_url = f"{self.BASE_URL}&page=1"
            resp = await session.get(first_url, headers=headers, timeout=25)
            if resp.status_code != 200:
                logger.warning(f"Sopra Steria page 1 returned HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            page_listings = self._extract_listings_from_soup(soup, seen_ids)
            listings.extend(page_listings)

            total_results = self._parse_total_results(soup)
            if total_results is not None:
                total_pages = max(1, math.ceil(total_results / 6))
            else:
                total_pages = 10

            logger.info(f"Sopra Steria total results: {total_results}, total pages: {total_pages}")

            if total_pages > 1:
                sem = asyncio.Semaphore(5)

                async def fetch_page(page_num: int) -> List[JobListing]:
                    async with sem:
                        url = f"{self.BASE_URL}&page={page_num}"
                        try:
                            r = await session.get(url, headers=headers, timeout=25)
                            if r.status_code == 200:
                                page_soup = BeautifulSoup(r.text, "html.parser")
                                return self._extract_listings_from_soup(page_soup, seen_ids)
                            else:
                                logger.warning(f"Sopra Steria page {page_num} returned HTTP {r.status_code}")
                        except Exception as e:
                            logger.error(f"Error fetching Sopra Steria page {page_num}: {e}")
                        return []

                tasks = [fetch_page(p) for p in range(2, total_pages + 1)]
                results = await asyncio.gather(*tasks)
                for res in results:
                    listings.extend(res)

        logger.info(f"Sopra Steria curl scraped {len(listings)} jobs.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """
        Fallback scraping using Playwright if curl_cffi fails.
        """
        logger.info("Attempting Sopra Steria careers scraping via Playwright fallback...")
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

                # Fetch page 1
                await page.goto(f"{self.BASE_URL}&page=1", wait_until="domcontentloaded", timeout=40000)
                await asyncio.sleep(2)

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                page_listings = self._extract_listings_from_soup(soup, seen_ids)
                listings.extend(page_listings)

                total_results = self._parse_total_results(soup)
                total_pages = max(1, math.ceil(total_results / 6)) if total_results else 10

                for page_num in range(2, total_pages + 1):
                    await page.goto(f"{self.BASE_URL}&page={page_num}", wait_until="domcontentloaded", timeout=40000)
                    await asyncio.sleep(1.5)
                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    cur_listings = self._extract_listings_from_soup(soup, seen_ids)
                    if not cur_listings:
                        break
                    listings.extend(cur_listings)

            except Exception as e:
                logger.error(f"Playwright scraping error for Sopra Steria: {e}")
            finally:
                await browser.close()

        logger.info(f"Sopra Steria Playwright scraped {len(listings)} jobs.")
        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Sopra Steria curl scrape returned 0 jobs. Falling back to Playwright...")
        except Exception as e:
            logger.error(f"Sopra Steria curl scrape failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Sopra Steria Playwright scrape failed: {e}")
            return []
