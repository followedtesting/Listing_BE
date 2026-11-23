import asyncio
import gc
import json
import logging
import re
from typing import List, Set, Dict, Any, Optional
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class ThalesPortalAdapter(BaseJobAdapter):
    """
    Adapter for Thales Careers Portal (Phenom People platform).
    Target URL: https://careers.thalesgroup.com/global/en/search-results
    
    Filters:
      - Country: "India"
      - Category: "Software"
      
    Network Architecture:
      - Platform: Phenom People
      - Primary: POST https://careers.thalesgroup.com/widgets with refineSearch payload:
        selected_fields: {"country": ["India"], "category": ["Software"]}
      - Secondary Fallback: Headless Playwright browser automation
    """

    TARGET_URL = "https://careers.thalesgroup.com/global/en/search-results"
    BASE_URL = "https://careers.thalesgroup.com"
    WIDGETS_URL = "https://careers.thalesgroup.com/widgets"
    BASE_JOB_URL = "https://careers.thalesgroup.com/global/en/job"

    SELECTED_FIELDS = {
        "country": ["India"],
        "category": ["Software"],
    }

    @property
    def portal_id(self) -> str:
        return "thales_careers"

    @property
    def portal_name(self) -> str:
        return "Thales Careers Portal"

    def _parse_job_items(self, jobs: List[Dict[str, Any]], seen_ids: Set[str]) -> List[JobListing]:
        """Parses Phenom People job items into JobListing instances."""
        listings: List[JobListing] = []

        for j in jobs:
            job_id = str(j.get("reqId") or j.get("jobId") or j.get("jobSeqNo") or "").strip()
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
            location = ", ".join(loc_parts) if loc_parts else "India"
            if "india" not in location.lower():
                location = f"{location}, India"

            job_link = f"{self.BASE_JOB_URL}/{job_id}"

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=job_link,
                    location=location,
                )
            )

        return listings

    def _get_payload(self, page_id: str, offset: int, size: int) -> Dict[str, Any]:
        """Builds the Phenom widgets API request payload."""
        return {
            "lang": "en_global",
            "deviceType": "desktop",
            "country": "global",
            "pageName": "search-results",
            "ddoKey": "refineSearch",
            "appId": "",
            "pageId": page_id,
            "pageUrl": self.TARGET_URL,
            "jobs": True,
            "counts": True,
            "all_fields": ["category", "country", "state", "city"],
            "selected_fields": self.SELECTED_FIELDS,
            "locationData": {},
            "from": offset,
            "size": size,
        }

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes Thales Careers via Phenom People /widgets API using curl_cffi."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        size = 50
        max_pages = 20

        async with AsyncSession(impersonate="chrome124") as session:
            # 1. Fetch initial search page to acquire session cookies, csrfToken, and pageId
            init_resp = await session.get(self.TARGET_URL, headers=headers, timeout=25)
            if init_resp.status_code != 200:
                logger.warning(f"Thales search-results initial page returned status {init_resp.status_code}")
                return []

            csrf_match = re.search(r'"?csrfToken"?\s*:\s*"([^"]+)"', init_resp.text)
            csrf_token = csrf_match.group(1) if csrf_match else ""
            page_id_match = re.search(r'"?pageId"?\s*:\s*"([^"]+)"', init_resp.text)
            page_id = page_id_match.group(1) if page_id_match else "page18"

            post_headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": self.BASE_URL,
                "Referer": self.TARGET_URL,
                "X-Requested-With": "XMLHttpRequest",
            }
            if csrf_token:
                post_headers["X-CSRF-TOKEN"] = csrf_token

            offset = 0
            for page in range(1, max_pages + 1):
                payload = self._get_payload(page_id=page_id, offset=offset, size=size)
                resp = await session.post(self.WIDGETS_URL, json=payload, headers=post_headers, timeout=25)
                if resp.status_code != 200:
                    logger.warning(f"Thales /widgets returned HTTP {resp.status_code} on page {page}")
                    break

                try:
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Failed to parse Thales /widgets JSON on page {page}: {e}")
                    break

                refine = data.get("refineSearch", {})
                total_hits = refine.get("totalHits", 0)
                batch_jobs = refine.get("data", {}).get("jobs", [])

                page_listings = self._parse_job_items(batch_jobs, seen_ids)
                listings.extend(page_listings)
                logger.info(
                    f"Thales page {page}: fetched {len(page_listings)} jobs (total so far: {len(listings)}, totalHits: {total_hits})"
                )

                if len(listings) >= total_hits or not batch_jobs:
                    break

                offset += size

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Headless Playwright fallback for Thales Careers portal."""
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

                # Block heavy assets to keep memory minimal
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ["image", "media", "font"]
                    else route.continue_(),
                )

                logger.info(f"Navigating to Thales Careers portal: {self.TARGET_URL}")
                await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                # Fetch jobs via the page's authenticated session in browser context
                raw_jobs = await page.evaluate("""async () => {
                    const csrf = window.phApp?.ddo?.siteConfig?.data?.csrfToken || '';
                    const pageId = window.phApp?.pageId || 'page18';
                    const payload = {
                        lang: 'en_global',
                        deviceType: 'desktop',
                        country: 'global',
                        pageName: 'search-results',
                        ddoKey: 'refineSearch',
                        appId: '',
                        pageId: pageId,
                        pageUrl: window.location.href,
                        jobs: true,
                        counts: true,
                        all_fields: ['category', 'country', 'state', 'city'],
                        selected_fields: {
                            country: ['India'],
                            category: ['Software']
                        },
                        locationData: {},
                        from: 0,
                        size: 50
                    };
                    const headers = {
                        'Content-Type': 'application/json;charset=UTF-8',
                        'Accept': 'application/json, text/plain, */*',
                        'X-Requested-With': 'XMLHttpRequest'
                    };
                    if (csrf) headers['X-CSRF-TOKEN'] = csrf;
                    
                    const resp = await fetch('https://careers.thalesgroup.com/widgets', {
                        method: 'POST',
                        headers: headers,
                        body: JSON.stringify(payload)
                    });
                    const data = await resp.json();
                    return data?.refineSearch?.data?.jobs || [];
                }""")

                if raw_jobs:
                    listings = self._parse_job_items(raw_jobs, seen_ids)

        except Exception as e:
            logger.error(f"Playwright scraping failed for Thales Careers: {e}")
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
                logger.info(f"Thales portal scraped {len(listings)} jobs via curl_cffi")
                return listings
            logger.warning("Thales curl_cffi returned 0 jobs, falling back to Playwright")
        except Exception as e:
            logger.warning(f"Thales curl_cffi failed ({e}), falling back to Playwright")

        listings = await self._scrape_playwright()
        logger.info(f"Thales portal scraped {len(listings)} jobs via Playwright")
        return listings
