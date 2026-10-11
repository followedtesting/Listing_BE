import logging
import asyncio
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MetaformsPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "metaforms_careers"

    @property
    def portal_name(self) -> str:
        return "Metaforms Careers Portal"

    def _parse_api_jobs(self, jobs: list, seen_ids: Set[str], target_dept: str = "Engineering") -> List[JobListing]:
        listings = []
        dept_lower = target_dept.lower()

        for j in jobs:
            dept = (j.get("department") or "").strip().lower()
            team = (j.get("team") or "").strip().lower()
            if dept != dept_lower and team != dept_lower:
                continue

            job_id = str(j.get("id", "")).strip()
            title = (j.get("title") or "").strip()
            link = (j.get("jobUrl") or f"https://jobs.ashbyhq.com/metaforms/{job_id}").strip()

            # Location formatting
            addr = j.get("address", {}).get("postalAddress", {})
            locality = addr.get("addressLocality", "")
            country = addr.get("addressCountry", "")
            loc_str = j.get("location", "")
            if locality and country:
                location = f"{locality}, {country}"
            elif loc_str:
                location = loc_str
            else:
                location = "Bengaluru, India"

            if not job_id or not title or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            listings.append(JobListing(
                jobid=job_id,
                role_name=title,
                job_listing_link=link,
                location=location
            ))

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        api_url = "https://api.ashbyhq.com/posting-api/job-board/metaforms"
        logger.info(f"Fetching Metaforms jobs from Ashby API: {api_url}")
        seen_ids = set()

        async with AsyncSession(impersonate="chrome124") as s:
            res = await s.get(api_url, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                jobs = data.get("jobs", [])
                return self._parse_api_jobs(jobs, seen_ids, target_dept="Engineering")
            else:
                logger.warning(f"Ashby API returned status {res.status_code} for Metaforms")

        return []

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Metaforms scrape via Playwright browser session fallback...")
        target_url = "https://jobs.ashbyhq.com/metaforms?departmentId=1d630a0c-2585-4136-b105-817645945703"
        listings = []
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
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    logger.warning(f"Playwright navigation warning on Metaforms careers page: {e}")

                # First try fetching from internal Ashby posting API via browser fetch
                api_data = await page.evaluate("""async () => {
                    try {
                        let res = await fetch("https://api.ashbyhq.com/posting-api/job-board/metaforms");
                        if (!res.ok) return null;
                        return await res.json();
                    } catch(e) {
                        return null;
                    }
                }""")

                if api_data and isinstance(api_data, dict):
                    jobs = api_data.get("jobs", [])
                    listings = self._parse_api_jobs(jobs, seen_ids, target_dept="Engineering")
                    if listings:
                        return listings

                # DOM extraction fallback
                dom_jobs = await page.evaluate("""() => {
                    let links = Array.from(document.querySelectorAll('a')).filter(l => l.href.includes('/metaforms/'));
                    return links.map(l => ({
                        href: l.href,
                        text: l.innerText ? l.innerText.trim() : ''
                    }));
                }""")

                for dj in dom_jobs:
                    link = dj.get("href", "")
                    text = dj.get("text", "")
                    match = re.search(r'/metaforms/([a-f0-9\-]+)', link)
                    job_id = match.group(1) if match else ""
                    if not job_id or job_id in seen_ids:
                        continue

                    # Text format: "AI Security & Platform Engineer\n\nEngineering • Bengaluru • Full time • On-site"
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    title = lines[0] if lines else ""
                    location = "Bengaluru, India"
                    for line in lines[1:]:
                        if "Bengaluru" in line or "India" in line or "Remote" in line:
                            location = line
                            break

                    if title:
                        seen_ids.add(job_id)
                        listings.append(JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=link,
                            location=location
                        ))

            except Exception as pe:
                logger.error(f"Playwright fallback failed for Metaforms: {pe}")
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Finished Metaforms Careers HTTP scrape. Found {len(listings)} Engineering listings.")
                return listings
        except Exception as e:
            logger.warning(f"Metaforms HTTP scrape failed: {e}. Trying Playwright fallback...")

        try:
            listings = await self._scrape_playwright()
            logger.info(f"Finished Metaforms Careers Playwright fallback scrape. Found {len(listings)} Engineering listings.")
            return listings
        except Exception as e:
            logger.error(f"Error in Metaforms portal Playwright fallback: {e}", exc_info=True)
            return []
