import asyncio
import gc
import json
import logging
from typing import List, Set, Dict, Any, Optional
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class HPEPortalAdapter(BaseJobAdapter):
    """
    Adapter for Hewlett Packard Enterprise (HPE) Careers Portal (Phenom People platform).
    Target URL: https://careers.hpe.com/us/en/search-results?rk=page-targeted-jobs-page72-prod-6cd8yjVP&sortBy=Most%20relevant
    Filters:
      - Country: "India"
      - Category: "Engineering & QA"
    Network Call:
      - POST https://careers.hpe.com/widgets with selected_fields:
        {"country": ["India"], "category": ["Engineering & QA"]}
    """

    TARGET_URL = (
        "https://careers.hpe.com/us/en/search-results"
        "?rk=page-targeted-jobs-page72-prod-6cd8yjVP&sortBy=Most%20relevant"
    )
    WIDGETS_URL = "https://careers.hpe.com/widgets"
    BASE_JOB_URL = "https://careers.hpe.com/us/en/job"
    PAGE_ID = "page15"

    SELECTED_FIELDS = {
        "country": ["India"],
        "category": ["Engineering & QA"],
    }

    @property
    def portal_id(self) -> str:
        return "hpe_careers"

    @property
    def portal_name(self) -> str:
        return "HPE Careers Portal"

    def _parse_job_items(self, jobs: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        """Parses Phenom job items into JobListing instances."""
        listings: List[JobListing] = []
        for j in jobs:
            job_id = str(j.get("reqId") or j.get("jobId") or "").strip()
            title = (j.get("title") or "").strip()

            if not job_id or not title:
                continue

            if job_id in seen_ids:
                continue

            seen_ids.add(job_id)

            city = (j.get("city") or "").strip()
            state = (j.get("state") or "").strip()
            country = (j.get("country") or "").strip() or "India"

            loc_parts = [p for p in [city, state, country] if p]
            loc_str = ", ".join(loc_parts) if loc_parts else "India"
            if "india" not in loc_str.lower():
                loc_str = f"{loc_str}, India"

            link = f"{self.BASE_JOB_URL}/{job_id}"

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=link,
                    location=loc_str,
                )
            )
        return listings

    def _build_payload(self, offset: int, size: int) -> Dict[str, Any]:
        """Constructs the JSON request payload for the Phenom /widgets endpoint."""
        return {
            "lang": "en_us",
            "deviceType": "desktop",
            "country": "us",
            "pageName": "search-results",
            "ddoKey": "refineSearch",
            "sortBy": "Most relevant",
            "subsearch": "",
            "from": offset,
            "irs": False,
            "jobs": True,
            "counts": True,
            "all_fields": ["category", "country", "state", "city"],
            "size": size,
            "clearAll": False,
            "jdsource": "facets",
            "isSliderEnable": False,
            "pageId": self.PAGE_ID,
            "siteType": "external",
            "keywords": "",
            "global": True,
            "selected_fields": self.SELECTED_FIELDS,
            "locationData": {},
        }

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes HPE Phenom widgets API using high-performance curl_cffi."""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://careers.hpe.com",
            "Referer": self.TARGET_URL,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        size = 50
        total_hits = None

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                payload = self._build_payload(offset, size)
                resp = await session.post(self.WIDGETS_URL, json=payload, headers=headers, timeout=25)

                if resp.status_code != 200:
                    logger.warning(f"HPE Phenom API returned HTTP {resp.status_code} at offset {offset}")
                    break

                try:
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Failed to parse JSON response from HPE widgets: {e}")
                    break

                refine = data.get("refineSearch", {})
                if total_hits is None and "totalHits" in refine:
                    total_hits = refine.get("totalHits")

                jobs = refine.get("data", {}).get("jobs", [])
                if not jobs:
                    break

                batch = self._parse_job_items(jobs, seen_ids)
                listings.extend(batch)

                offset += size
                if total_hits is not None and offset >= total_hits:
                    break
                if len(jobs) < size:
                    break

        logger.info(f"HPE curl scraped {len(listings)} Engineering & QA jobs in India (total hits: {total_hits}).")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Low-RAM Playwright fallback for HPE Phenom widgets."""
        logger.info("Attempting HPE scraping via Playwright fallback...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        size = 50
        total_hits = None
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
            await asyncio.sleep(2)

            while True:
                payload = self._build_payload(offset, size)

                data = await page.evaluate(
                    """
                    async (p) => {
                        try {
                            const res = await fetch('/widgets', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json'
                                },
                                body: JSON.stringify(p)
                            });
                            return await res.json();
                        } catch (e) {
                            return { "error": e.message };
                        }
                    }
                    """,
                    payload,
                )

                if not isinstance(data, dict) or "error" in data:
                    logger.error(f"Error fetching HPE jobs in Playwright at offset {offset}: {data}")
                    break

                refine = data.get("refineSearch", {})
                if total_hits is None and "totalHits" in refine:
                    total_hits = refine.get("totalHits")

                jobs = refine.get("data", {}).get("jobs", [])
                if not jobs:
                    break

                batch = self._parse_job_items(jobs, seen_ids)
                listings.extend(batch)

                offset += size
                if total_hits is not None and offset >= total_hits:
                    break
                if len(jobs) < size:
                    break

            logger.info(f"HPE Playwright scraped {len(listings)} jobs.")
        except Exception as e:
            logger.error(f"Playwright scraping error for HPE: {e}", exc_info=True)
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
        """Scrapes HPE Engineering & QA jobs in India with curl primary and Playwright fallback."""
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("HPE curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"HPE curl scraping failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"HPE Playwright scraping failed: {e}")
            return []
