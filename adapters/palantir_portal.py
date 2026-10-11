import logging
import asyncio
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PalantirPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "palantir_careers"

    @property
    def portal_name(self) -> str:
        return "Palantir Careers Portal"

    def _parse_lever_jobs(self, raw_jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for j in raw_jobs:
            tags = j.get("tags") or []
            # Match business area filter: 'Commercial||Engineering' on the page selects
            # all postings matching the Engineering subcategory (displayed across ~20 cards)
            matches_business_area = any(
                "subcategory:engineering" in t.lower()
                or ("commercial" in t.lower() and "engineering" in t.lower())
                for t in tags
            )
            if not matches_business_area:
                continue

            job_id = str(j.get("id") or "").strip()
            title = (j.get("text") or "").strip()

            urls_obj = j.get("urls") or {}
            link = (
                urls_obj.get("show")
                or j.get("hostedUrl")
                or f"https://jobs.lever.co/palantir/{job_id}"
            ).strip()

            categories = j.get("categories") or {}
            loc = categories.get("location")
            if not loc:
                all_locs = categories.get("allLocations") or []
                loc = ", ".join(all_locs) if all_locs else "Multiple Locations"

            if not job_id or not title or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=link,
                    location=loc.strip()
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        base_api_url = "https://www.palantir.com/api/lever/v1/postings?state=published"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.palantir.com/careers/open-positions/?business-area=Commercial%7C%7CEngineering",
            "Origin": "https://www.palantir.com",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        next_token = None

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                fetch_url = base_api_url if not next_token else f"{base_api_url}&offset={next_token}"
                resp = await session.get(fetch_url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    logger.warning(f"Palantir Lever API returned HTTP {resp.status_code}")
                    break

                data = resp.json()
                raw_jobs = data.get("data", []) if isinstance(data, dict) else []
                batch = self._parse_lever_jobs(raw_jobs, seen_ids)
                listings.extend(batch)

                if data.get("hasNext") and data.get("next"):
                    next_token = data.get("next")
                else:
                    break

        logger.info(f"Palantir curl scraped {len(listings)} Commercial Engineering jobs.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Palantir careers scraping via Playwright...")
        target_url = "https://www.palantir.com/careers/open-positions/?business-area=Commercial%7C%7CEngineering"
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
                await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)

                # Fetch jobs via in-page evaluate using page session context
                all_raw_jobs = await page.evaluate("""
                    async () => {
                        let all = [];
                        let next = null;
                        while (true) {
                            let url = "/api/lever/v1/postings?state=published" + (next ? "&offset=" + next : "");
                            let res = await fetch(url);
                            let json = await res.json();
                            all = all.concat(json.data || []);
                            if (json.hasNext && json.next) {
                                next = json.next;
                            } else {
                                break;
                            }
                        }
                        return all;
                    }
                """)

                if all_raw_jobs and isinstance(all_raw_jobs, list):
                    listings = self._parse_lever_jobs(all_raw_jobs, seen_ids)

                logger.info(f"Palantir Playwright scraped {len(listings)} jobs.")
            except Exception as e:
                logger.error(f"Playwright scraping error for Palantir: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. High performance curl_cffi direct API queries
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Palantir curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"Palantir curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright in-browser fetch fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Palantir Playwright scraping also failed: {e}")
            return []
