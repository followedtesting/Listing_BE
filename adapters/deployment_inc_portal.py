import asyncio
import gc
import json
import logging
import re
from typing import List, Set, Dict, Any, Optional
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class DeploymentIncPortalAdapter(BaseJobAdapter):
    """
    Adapter for Deployment Inc Careers Portal.
    Target URL: https://deployment.inc/careers/#roles
    
    Structure:
      - Static HTML with Schema.org JSON-LD and semantic `.role-row` links.
      - Primary: High-speed HTTP GET via curl_cffi AsyncSession.
      - Secondary Fallback: Headless Playwright browser automation.
    """

    TARGET_URL = "https://deployment.inc/careers/#roles"
    BASE_URL = "https://deployment.inc"
    PAGE_URL = "https://deployment.inc/careers/"

    @property
    def portal_id(self) -> str:
        return "deployment_inc_careers"

    @property
    def portal_name(self) -> str:
        return "Deployment Inc Careers Portal"

    def _parse_html(self, html: str, seen_ids: Set[str]) -> List[JobListing]:
        """Parses the careers HTML page into JobListing objects."""
        listings: List[JobListing] = []
        soup = BeautifulSoup(html, "html.parser")

        # 1. First attempt: Parse semantic .role-row links inside #roles
        roles_section = soup.find(id="roles") or soup
        cards = roles_section.select("a.role-row, a[href*='/careers/']")

        for c in cards:
            href = (c.get("href") or "").strip()
            if not href or href == "#" or href.rstrip("/") == "/careers":
                continue

            title_el = c.select_one(".role-row__title, h3, h2")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            meta_el = c.select_one(".role-row__meta")
            meta_text = meta_el.get_text(strip=True) if meta_el else ""

            # Extract location from meta (format: 'Department · Location', e.g. 'Engineering · Gurugram')
            if "·" in meta_text:
                parts = [p.strip() for p in meta_text.split("·")]
                loc = parts[-1]
            else:
                loc = meta_text or "Gurugram, India"

            if loc and "india" not in loc.lower():
                loc = f"{loc}, India"

            full_link = f"{self.BASE_URL}{href}" if href.startswith("/") else href
            slug = href.strip("/").split("/")[-1]
            job_id = slug or re.sub(r"[^a-zA-Z0-9_-]", "-", title.lower())

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location=loc,
                )
            )

        # 2. Fallback attempt: Parse Schema.org JSON-LD ItemList if DOM parsing yielded no items
        if not listings:
            for s in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(s.string or "{}")
                    if data.get("@type") == "ItemList":
                        items = data.get("itemListElement", [])
                        for item in items:
                            url = item.get("url", "")
                            name = item.get("name", "")
                            if not url or not name:
                                continue

                            slug = url.strip("/").split("/")[-1]
                            job_id = slug or name.lower().replace(" ", "-")
                            if job_id in seen_ids:
                                continue
                            seen_ids.add(job_id)

                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=name,
                                    job_listing_link=url,
                                    location="Gurugram, India",
                                )
                            )
                except Exception:
                    continue

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes Deployment Inc careers page via high-performance curl_cffi AsyncSession."""
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(self.PAGE_URL, headers=headers, timeout=25)
            if resp.status_code != 200:
                logger.warning(f"Deployment Inc careers page returned status {resp.status_code}")
                return []

            listings = self._parse_html(resp.text, seen_ids)
            logger.info(f"Deployment Inc curl_cffi successfully parsed {len(listings)} listings")
            return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Headless Playwright browser fallback for Deployment Inc careers portal."""
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        browser = None
        context = None
        page = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--single-process",
                    ],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                # Block heavy media assets to minimize memory footprint
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ["image", "media", "font"]
                    else route.continue_(),
                )

                logger.info(f"Navigating to Deployment Inc portal: {self.TARGET_URL}")
                await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector(".role-row, #roles", timeout=10000)

                content = await page.content()
                listings = self._parse_html(content, seen_ids)

        except Exception as e:
            logger.error(f"Playwright scraping failed for Deployment Inc: {e}")
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            gc.collect()

        return listings

    async def scrape(self) -> List[JobListing]:
        """Main entry point: attempts high-speed curl_cffi first, falls back to Playwright."""
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Deployment Inc portal scraped {len(listings)} jobs via curl_cffi")
                return listings
            logger.warning("Deployment Inc curl_cffi returned 0 jobs, falling back to Playwright")
        except Exception as e:
            logger.warning(f"Deployment Inc curl_cffi failed ({e}), falling back to Playwright")

        listings = await self._scrape_playwright()
        logger.info(f"Deployment Inc portal scraped {len(listings)} jobs via Playwright")
        return listings
