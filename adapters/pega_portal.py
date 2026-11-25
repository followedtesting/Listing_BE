import asyncio
import gc
import logging
import re
from typing import List, Set, Dict, Any, Optional
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class PegaPortalAdapter(BaseJobAdapter):
    """
    Adapter for Pegasystems (Pega) Careers Portal.
    Target URL: https://www.pega.com/about/careers/job-listings?f%5B0%5D=category%3A24351&f%5B1%5D=category%3A38341

    Filters:
      - Category 24351: "Engineering & Cloud"
      - Category 38341: "Product Engineering"

    Network & Platform Architecture:
      - Platform: Drupal 9/10 CMS with Bolt Design System
      - The main aggregator page (`/about/careers/job-listings`) is guarded by strict Cloudflare WAF bot challenges.
      - However, the official XML sitemap (`https://www.pega.com/sitemap.xml`) is fully accessible and maintains
        real-time indexed links for all active career opportunities (`/about/careers/{job_id}/{slug}`).
      - Individual job posting pages are accessible directly via HTTP 200 without Cloudflare challenges.
      - On each job detail page:
        - Job Category: `<div class="u-bolt-margin-bottom-xsmall">Job Category: ...</div>`
        - Location: `<div class="u-bolt-margin-bottom-xsmall">Location: ...</div>`
        - Role Name: `<h1>...</h1>`
        - Requisition ID: Extracted from URL path `r"/careers/(\\d+)/"`
      - Primary Extraction: High-performance concurrent HTTP GETs via curl_cffi AsyncSession (with semaphore concurrency control).
      - Secondary Fallback: Headless Playwright browser automation.
    """

    TARGET_URL = (
        "https://www.pega.com/about/careers/job-listings"
        "?f%5B0%5D=category%3A24351&f%5B1%5D=category%3A38341"
    )
    BASE_URL = "https://www.pega.com"
    SITEMAP_URL = "https://www.pega.com/sitemap.xml"

    # Mapped Drupal taxonomy term IDs:
    # 24351 -> "Engineering & Cloud"
    # 38341 -> "Product Engineering"
    TARGET_CATEGORIES = {
        "engineering & cloud",
        "product engineering",
    }

    CONCURRENCY_LIMIT = 10

    @property
    def portal_id(self) -> str:
        return "pega_careers"

    @property
    def portal_name(self) -> str:
        return "Pegasystems Careers Portal"

    def _normalize_location(self, raw_loc: str) -> str:
        """Normalizes location strings (e.g. 'India - Karnataka - Bangalore' -> 'Bangalore, Karnataka, India')."""
        loc = raw_loc.strip()
        if not loc:
            return "Global"

        # Handle multiple locations separated by pipe
        if "|" in loc:
            parts = [self._normalize_location(p) for p in loc.split("|")]
            return " | ".join(parts)

        # Standardize "Country - Region - City" format
        segments = [s.strip() for s in loc.split("-") if s.strip()]
        if len(segments) == 3 and segments[0].lower() in ["india", "us", "uk"]:
            # Rearrange to "City, Region, Country"
            return f"{segments[2]}, {segments[1]}, {segments[0]}"
        elif len(segments) == 2 and segments[0].lower() in ["india", "poland", "japan"]:
            return f"{segments[1]}, {segments[0]}"

        return loc

    async def _fetch_job_detail(
        self, session: AsyncSession, url: str, semaphore: asyncio.Semaphore, seen_ids: Set[str]
    ) -> Optional[JobListing]:
        """Fetches and parses an individual Pega job listing page."""
        m_id = re.search(r"/careers/(\d+)/", url)
        job_id = m_id.group(1) if m_id else url

        if job_id in seen_ids:
            return None

        async with semaphore:
            try:
                response = await session.get(url, timeout=15)
                if response.status_code != 200:
                    return None

                soup = BeautifulSoup(response.text, "html.parser")
                h1 = soup.find("h1")
                if not h1:
                    return None

                title = h1.get_text(strip=True)
                if not title:
                    return None

                category = ""
                raw_loc = ""

                meta_divs = soup.find_all("div", class_="u-bolt-margin-bottom-xsmall")
                for md in meta_divs:
                    t = md.get_text(strip=True)
                    if "job category:" in t.lower():
                        category = t.split(":", 1)[1].strip()
                    elif "location:" in t.lower():
                        raw_loc = t.split(":", 1)[1].strip()

                if category.lower() not in self.TARGET_CATEGORIES:
                    return None

                seen_ids.add(job_id)
                location = self._normalize_location(raw_loc)

                return JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=url,
                    location=location,
                )

            except Exception as e:
                logger.debug(f"[{self.portal_id}] Failed fetching {url}: {e}")
                return None

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes Pega job listings matching target categories via curl_cffi and XML sitemap."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.pega.com/about/careers",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124", headers=headers) as session:
            logger.info(f"[{self.portal_id}] Fetching Pega sitemap from {self.SITEMAP_URL}...")
            resp = await session.get(self.SITEMAP_URL, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"[{self.portal_id}] Failed to fetch sitemap: HTTP {resp.status_code}")
                return []

            career_urls = re.findall(
                r"<loc>\s*(https://www\.pega\.com/about/careers/\d+/[^<]+)\s*</loc>",
                resp.text,
            )
            logger.info(
                f"[{self.portal_id}] Discovered {len(career_urls)} active career URLs in sitemap"
            )

            semaphore = asyncio.Semaphore(self.CONCURRENCY_LIMIT)
            tasks = [
                self._fetch_job_detail(session, u, semaphore, seen_ids) for u in career_urls
            ]
            results = await asyncio.gather(*tasks)

            for item in results:
                if item:
                    listings.append(item)

        logger.info(
            f"[{self.portal_id}] Successfully extracted {len(listings)} listings matching categories: {self.TARGET_CATEGORIES}"
        )
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Secondary fallback: Scrapes via headless Playwright browser."""
        logger.info(f"[{self.portal_id}] Starting Playwright fallback...")
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
                    "--disable-extensions",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                # Remove navigator.webdriver detection
                await page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                )

                logger.info(f"[{self.portal_id}] [Playwright] Navigating to {self.TARGET_URL}")
                await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(3000)

                # Attempt to extract job links if Cloudflare is cleared or rendered
                job_links = await page.locator("a[href*='/about/careers/']").all()
                for link_el in job_links:
                    href = (await link_el.get_attribute("href") or "").strip()
                    title = (await link_el.inner_text()).strip()
                    if not href or not title or not re.search(r"/\d+/", href):
                        continue

                    m = re.search(r"/careers/(\d+)/", href)
                    job_id = m.group(1) if m else href

                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=full_url,
                            location="Global",
                        )
                    )

            except Exception as e:
                logger.error(f"[{self.portal_id}] Playwright fallback encountered error: {e}")
            finally:
                try:
                    await page.close()
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

        return listings

    async def scrape(self) -> List[JobListing]:
        """Main scraping entrypoint: tries curl_cffi + sitemap first, falls back to Playwright."""
        logger.info(f"[{self.portal_id}] Starting job scrape for {self.portal_name}...")
        listings: List[JobListing] = []

        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(
                    f"[{self.portal_id}] Successfully extracted {len(listings)} listings via curl_cffi"
                )
                return listings
            logger.warning(f"[{self.portal_id}] curl_cffi returned 0 listings, falling back to Playwright")
        except Exception as e:
            logger.warning(f"[{self.portal_id}] curl_cffi scrape failed: {e}. Falling back to Playwright")

        try:
            listings = await self._scrape_playwright()
            logger.info(
                f"[{self.portal_id}] Playwright fallback finished with {len(listings)} listings"
            )
        except Exception as e:
            logger.error(f"[{self.portal_id}] Playwright fallback failed: {e}")

        gc.collect()
        return listings
