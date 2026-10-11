import logging
import asyncio
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ZeptoPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "zepto_careers"

    @property
    def portal_name(self) -> str:
        return "Zepto Careers Portal"

    def _clean_location(self, loc: str) -> str:
        if not loc:
            return "Bengaluru, India"
        cleaned = re.sub(r'[\r\n]+', ' ', loc)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    def _parse_jobs(self, jobs: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for idx, j in enumerate(jobs):
            job_id = str(j.get("id") or j.get("_id") or f"zepto_{idx}").strip()
            title = (j.get("title") or j.get("designation_name") or "").strip()

            raw_loc = ""
            loc_list = j.get("officelocation_show_arr_list")
            if loc_list and isinstance(loc_list, list) and len(loc_list) > 0:
                raw_loc = loc_list[0]
            if not raw_loc:
                raw_loc = j.get("locations") or j.get("country") or "India"

            location = self._clean_location(raw_loc)
            link = f"https://zepto.darwinbox.in/ms/candidatev2/main/careers/jobDetails/{job_id}"

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
            "Referer": "https://zepto.darwinbox.in/ms/candidatev2/main/careers/allJobs",
            "Content-Type": "application/json",
        }

        api_url = "https://zepto.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main"
        logger.info(f"Fetching Zepto jobs from Darwinbox API: {api_url}")
        seen_ids = set()

        async with AsyncSession(impersonate="chrome124") as s:
            res = await s.post(api_url, json={}, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                jobs = data.get("data", [])
                return self._parse_jobs(jobs, seen_ids)
            else:
                logger.warning(f"Zepto Darwinbox API returned status {res.status_code}")

        return []

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Zepto scrape via Playwright browser session fallback...")
        target_url = "https://zepto.darwinbox.in/ms/candidatev2/main/careers/allJobs"
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
                    await page.wait_for_timeout(4000)
                except Exception as e:
                    logger.warning(f"Playwright navigation warning on Zepto careers page: {e}")

                # Evaluate fetch inside browser session
                api_data = await page.evaluate("""async () => {
                    try {
                        let res = await fetch("https://zepto.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: "{}"
                        });
                        if (!res.ok) return null;
                        return await res.json();
                    } catch(e) {
                        return null;
                    }
                }""")

                if api_data and isinstance(api_data, dict):
                    jobs = api_data.get("data", [])
                    listings = self._parse_jobs(jobs, seen_ids)
                    if listings:
                        return listings

                # DOM link extraction fallback
                dom_jobs = await page.evaluate("""() => {
                    let links = Array.from(document.querySelectorAll('a')).filter(l => l.href.includes('/jobDetails/'));
                    return links.map(l => {
                        let card = l.closest('.job-card, [class*="job"], tr, li, div');
                        return {
                            href: l.href,
                            card_text: card ? card.innerText : l.innerText
                        };
                    });
                }""")

                for dj in dom_jobs:
                    link = dj.get("href", "")
                    card_text = dj.get("card_text", "")
                    match = re.search(r'/jobDetails/([a-zA-Z0-9]+)', link)
                    job_id = match.group(1) if match else ""
                    if not job_id or job_id in seen_ids:
                        continue

                    lines = [ln.strip() for ln in card_text.split("\n") if ln.strip()]
                    title = lines[0] if lines else "Job Opening"

                    seen_ids.add(job_id)
                    listings.append(JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=link,
                        location="Bengaluru, Karnataka, India"
                    ))

            except Exception as pe:
                logger.error(f"Playwright fallback failed for Zepto: {pe}")
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Finished Zepto Careers HTTP scrape. Found {len(listings)} listings.")
                return listings
        except Exception as e:
            logger.warning(f"Zepto HTTP scrape failed: {e}. Trying Playwright fallback...")

        try:
            listings = await self._scrape_playwright()
            logger.info(f"Finished Zepto Careers Playwright fallback scrape. Found {len(listings)} listings.")
            return listings
        except Exception as e:
            logger.error(f"Error in Zepto portal Playwright fallback: {e}", exc_info=True)
            return []
