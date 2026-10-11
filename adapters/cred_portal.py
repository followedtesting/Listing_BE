import logging
import asyncio
import json
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class CredPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "cred_careers"

    @property
    def portal_name(self) -> str:
        return "CRED Careers Portal"

    def _format_location(self, loc: str) -> str:
        loc = loc.strip()
        if not loc:
            return "Bengaluru, India"
        loc_cap = loc.title()
        if "India" not in loc_cap:
            return f"{loc_cap}, India"
        return loc_cap

    def _parse_jobs(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for j in jobs:
            job_id = str(j.get("id", "")).strip()
            title = (j.get("text") or "").strip()
            if not job_id or not title or job_id in seen_ids:
                continue

            cats = j.get("categories", {})
            raw_loc = cats.get("location", "") or "Bengaluru"
            location = self._format_location(raw_loc)

            urls = j.get("urls", {})
            link = urls.get("show") or j.get("hostedUrl") or f"https://jobs.lever.co/cred/{job_id}"

            seen_ids.add(job_id)
            listings.append(JobListing(
                jobid=job_id,
                role_name=title.title(),
                job_listing_link=link,
                location=location
            ))

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        seen_ids = set()
        async with AsyncSession(impersonate="chrome124") as s:
            # 1. Primary: Extract from __NEXT_DATA__ on CRED website
            try:
                url = "https://careers.cred.club/openings"
                logger.info(f"Fetching CRED openings from: {url}")
                res = await s.get(url, headers=headers, timeout=15)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    script = soup.find("script", id="__NEXT_DATA__")
                    if script and script.string:
                        data = json.loads(script.string)
                        jobs = data.get("props", {}).get("pageProps", {}).get("data", {}).get("data", [])
                        parsed = self._parse_jobs(jobs, seen_ids)
                        if parsed:
                            return parsed
            except Exception as e:
                logger.warning(f"Error parsing CRED __NEXT_DATA__: {e}")

            # 2. Secondary fallback: Lever public API
            try:
                lever_url = "https://api.lever.co/v0/postings/cred?mode=json"
                logger.info(f"Fetching CRED openings from Lever API fallback: {lever_url}")
                res_lever = await s.get(lever_url, headers={"Accept": "application/json"}, timeout=15)
                if res_lever.status_code == 200:
                    lever_data = res_lever.json()
                    parsed_lever = self._parse_jobs(lever_data, seen_ids)
                    if parsed_lever:
                        return parsed_lever
            except Exception as e:
                logger.warning(f"Error requesting CRED Lever API: {e}")

        return []

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting CRED scrape via Playwright browser session fallback...")
        seen_ids = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()

                try:
                    await page.goto("https://careers.cred.club/openings", wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    logger.warning(f"Playwright navigation warning on CRED openings page: {e}")

                # Extract __NEXT_DATA__ inside browser context
                next_data = await page.evaluate("""() => {
                    let script = document.getElementById('__NEXT_DATA__');
                    if (script && script.innerText) {
                        try {
                            return JSON.parse(script.innerText);
                        } catch(e) {
                            return null;
                        }
                    }
                    return null;
                }""")

                if next_data and isinstance(next_data, dict):
                    jobs = next_data.get("props", {}).get("pageProps", {}).get("data", {}).get("data", [])
                    listings = self._parse_jobs(jobs, seen_ids)
                    if listings:
                        return listings

                # DOM link extraction fallback
                dom_jobs = await page.evaluate("""() => {
                    let links = Array.from(document.querySelectorAll('a')).filter(a => a.href.includes('jobs.lever.co/cred/'));
                    return links.map(a => ({
                        href: a.href,
                        text: a.innerText ? a.innerText.trim() : ''
                    }));
                }""")

                for dj in dom_jobs:
                    link = dj.get("href", "")
                    title = dj.get("text", "")
                    match = re.search(r'/cred/([a-f0-9\-]+)', link)
                    job_id = match.group(1) if match else ""
                    if job_id and title and job_id not in seen_ids:
                        seen_ids.add(job_id)
                        listings.append(JobListing(
                            jobid=job_id,
                            role_name=title.title(),
                            job_listing_link=link,
                            location="Bengaluru, India"
                        ))

                return listings

            except Exception as pe:
                logger.error(f"Playwright fallback failed for CRED: {pe}")
            finally:
                await browser.close()

        return []

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Finished CRED Careers HTTP scrape. Found {len(listings)} listings.")
                return listings
        except Exception as e:
            logger.warning(f"CRED HTTP scrape failed: {e}. Trying Playwright fallback...")

        try:
            listings = await self._scrape_playwright()
            logger.info(f"Finished CRED Careers Playwright fallback scrape. Found {len(listings)} listings.")
            return listings
        except Exception as e:
            logger.error(f"Error in CRED portal Playwright fallback: {e}", exc_info=True)
            return []
