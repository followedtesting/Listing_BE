import asyncio
import gc
import logging
from typing import List, Set, Dict, Any, Optional
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class ImprovingPortalAdapter(BaseJobAdapter):
    """
    Adapter for Improving Careers Portal.
    Target URL: https://www.improving.com/careers/open-positions/#openpositions
    Network Call:
      - GET https://www.improving.com/api/jobs (used by Astro JobTable component)
    """

    TARGET_URL = "https://www.improving.com/careers/open-positions/#openpositions"
    BASE_URL = "https://www.improving.com"
    API_URL = "https://www.improving.com/api/jobs"

    @property
    def portal_id(self) -> str:
        return "improving_careers"

    @property
    def portal_name(self) -> str:
        return "Improving Careers Portal"

    def _parse_job_items(self, data: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        """Parses the /api/jobs JSON payload into JobListing instances."""
        listings: List[JobListing] = []

        for j in data:
            if not isinstance(j, dict):
                continue

            job_id = str(j.get("guid") or j.get("id") or "").strip()
            title = (j.get("title") or "").strip()

            if not job_id or not title:
                continue

            if job_id in seen_ids:
                continue

            seen_ids.add(job_id)

            # Format location
            loc = (j.get("location") or "").strip()
            country = (j.get("country") or "").strip()
            if loc and country and country.lower() not in loc.lower():
                location = f"{loc}, {country}"
            else:
                location = loc or country or "Remote"

            # Prefer canonical career details page on improving.com
            job_link = f"{self.BASE_URL}/careers/open-positions/details/?id={job_id}"
            if not job_link:
                job_link = j.get("applicationUrl") or j.get("link") or self.TARGET_URL

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=job_link,
                    location=location,
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes Improving careers via high-performance curl_cffi AsyncSession."""
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.TARGET_URL,
        }

        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(self.API_URL, headers=headers, timeout=25)
            if resp.status_code != 200:
                logger.warning(f"Improving /api/jobs endpoint returned HTTP {resp.status_code}")
                return []

            try:
                data = resp.json()
            except Exception as e:
                logger.error(f"Failed to parse JSON response from Improving /api/jobs: {e}")
                return []

            if not isinstance(data, list):
                logger.warning("Improving /api/jobs did not return a list")
                return []

            listings = self._parse_job_items(data, seen_ids)

        logger.info(f"Improving curl scraped {len(listings)} open positions.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Low-RAM Playwright fallback for Improving Careers."""
        logger.info("Attempting Improving Careers scraping via Playwright fallback...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
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

            await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=40000)

            data = await page.evaluate(
                """
                async () => {
                    try {
                        const res = await fetch("/api/jobs", {
                            headers: {
                                "Accept": "application/json"
                            }
                        });
                        return await res.json();
                    } catch (e) {
                        return { "error": e.message };
                    }
                }
                """
            )

            if isinstance(data, list):
                listings = self._parse_job_items(data, seen_ids)
            else:
                logger.error(f"Error fetching Improving jobs in Playwright: {data}")

            logger.info(f"Improving Playwright scraped {len(listings)} jobs.")
        except Exception as e:
            logger.error(f"Playwright scraping error for Improving: {e}", exc_info=True)
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
        """Scrapes Improving open positions with curl primary and Playwright fallback."""
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Improving curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"Improving curl scraping failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Improving Playwright scraping failed: {e}")
            return []
