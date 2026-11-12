import asyncio
import gc
import html
import logging
from typing import List, Set, Dict, Any, Optional
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class ShiprocketPortalAdapter(BaseJobAdapter):
    """
    Adapter for Shiprocket Careers Portal.
    Target URL: https://careers.shiprocket.in/
    Department: "Technical" (filters by CSS class `.job.technical` / Isotope button `data-filter=".technical"`
    or WordPress REST API endpoint `/wp-json/wp/v2/jobs?departments=5`).
    """

    TARGET_URL = "https://careers.shiprocket.in/"
    WP_API_URL = "https://careers.shiprocket.in/wp-json/wp/v2/jobs?departments=5"
    DEPARTMENT_SLUG = "technical"
    DEPARTMENT_ID = 5

    @property
    def portal_id(self) -> str:
        return "shiprocket_careers"

    @property
    def portal_name(self) -> str:
        return "Shiprocket Careers Portal"

    def _extract_listings_from_html(self, html_text: str, seen_ids: Set[str]) -> List[JobListing]:
        """Extracts technical job listings from HTML content."""
        listings: List[JobListing] = []
        soup = BeautifulSoup(html_text, "html.parser")

        # Select all job elements with technical class
        job_cards = soup.select(".job.technical")
        if not job_cards:
            # Fallback search in case class names vary slightly
            for j in soup.select(".job"):
                classes = j.get("class") or []
                if any("technical" in c.lower() for c in classes):
                    job_cards.append(j)

        for card in job_cards:
            title_el = card.select_one("h5, h4, h3, .title")
            title = title_el.get_text(strip=True) if title_el else ""

            link_el = card.select_one("a[href*='/jobs/']") or card.select_one("a")
            link = (link_el.get("href") or "").strip() if link_el else ""

            # Extract location
            loc_el = card.select_one(".location small, .location")
            loc_text = loc_el.get_text(strip=True) if loc_el else "Gurugram, India"
            if "india" not in loc_text.lower():
                location = f"{loc_text}, India"
            else:
                location = loc_text

            # Job ID from URL slug or link
            job_id = ""
            if link:
                clean_path = link.rstrip("/").split("/")[-1]
                if clean_path:
                    job_id = clean_path

            if not job_id and title:
                job_id = title.lower().replace(" ", "-")

            if job_id and title and job_id not in seen_ids:
                seen_ids.add(job_id)
                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=link or self.TARGET_URL,
                        location=location,
                    )
                )

        return listings

    def _extract_listings_from_json(self, json_data: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        """Extracts technical job listings from WordPress REST API response."""
        listings: List[JobListing] = []

        for item in json_data:
            job_id = str(item.get("id") or item.get("slug") or "").strip()
            raw_title = item.get("title", {}).get("rendered", "")
            title = html.unescape(raw_title).strip()
            link = (item.get("link") or "").strip()

            if not job_id or not title:
                continue

            if job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=link or self.TARGET_URL,
                    location="Gurugram, India",
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes Shiprocket careers using high-performance curl_cffi AsyncSession."""
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        async with AsyncSession(impersonate="chrome120") as s:
            # 1. Primary method: Fetch main careers page HTML
            try:
                resp = await s.get(self.TARGET_URL, headers=headers, timeout=25)
                if resp.status_code == 200 and resp.text:
                    listings = self._extract_listings_from_html(resp.text, seen_ids)
                    if listings:
                        logger.info(f"Shiprocket curl HTML scraped {len(listings)} technical jobs.")
                        return listings
            except Exception as e:
                logger.warning(f"Shiprocket curl HTML scrape failed: {e}. Trying WP REST API...")

            # 2. Secondary network call: WordPress REST API with departments=5 (Technical)
            try:
                api_headers = {
                    "Accept": "application/json",
                    "User-Agent": headers["User-Agent"],
                    "Referer": self.TARGET_URL,
                }
                api_resp = await s.get(self.WP_API_URL, headers=api_headers, timeout=20)
                if api_resp.status_code == 200:
                    api_data = api_resp.json()
                    if isinstance(api_data, list) and api_data:
                        listings = self._extract_listings_from_json(api_data, seen_ids)
                        if listings:
                            logger.info(f"Shiprocket WP REST API scraped {len(listings)} technical jobs.")
                            return listings
            except Exception as e:
                logger.warning(f"Shiprocket WP REST API scrape failed: {e}")

        return []

    async def _scrape_playwright(self) -> List[JobListing]:
        """Low-RAM Playwright fallback with manual frontend department selection."""
        logger.info("Attempting Shiprocket Careers scraping via Playwright fallback...")
        seen_ids: Set[str] = set()
        listings: List[JobListing] = []
        playwright_obj = None
        browser = None

        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                    "--disable-extensions",
                    "--js-flags=--max-old-space-size=128",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            # Abort heavy static assets to conserve RAM
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort(),
            )

            await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=35000)

            # Wait for job listings container
            try:
                await page.wait_for_selector(".job", timeout=10000)
            except Exception:
                pass

            # Manually choose department = "Technical" from frontend button if available
            try:
                tech_btn = await page.query_selector('button[data-filter=".technical"]')
                if tech_btn:
                    await tech_btn.click()
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug(f"Could not click technical filter button: {e}")

            html_content = await page.content()
            listings = self._extract_listings_from_html(html_content, seen_ids)

        except Exception as e:
            logger.error(f"Playwright scraping error for Shiprocket: {e}")
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

        logger.info(f"Shiprocket Playwright scraped {len(listings)} technical jobs.")
        return listings

    async def scrape(self) -> List[JobListing]:
        """Scrapes Shiprocket technical job listings with curl primary and Playwright fallback."""
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Shiprocket curl scrape returned 0 jobs. Falling back to Playwright...")
        except Exception as e:
            logger.error(f"Shiprocket curl scrape failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Shiprocket Playwright scrape failed: {e}")
            return []
