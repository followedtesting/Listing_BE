import logging
import asyncio
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class TargetPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "target_careers"

    @property
    def portal_name(self) -> str:
        return "Target Careers Portal"

    def _parse_results(self, results: list, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        for r in results:
            doc = r.get("document", {})
            job_id = doc.get("sys_id") or doc.get("postingid") or doc.get("requisitionid")
            title = (doc.get("title") or "").strip()

            if not job_id or not title or str(job_id) in seen_ids:
                continue

            seen_ids.add(str(job_id))

            rel_url = doc.get("url") or ""
            job_link = f"https://corporate.target.com{rel_url}" if rel_url.startswith("/") else rel_url

            city = (doc.get("city") or "").strip()
            state = (doc.get("state") or "").strip()
            country = (doc.get("country") or "").strip()
            loc_parts = [p for p in [city, state, country] if p]
            location = ", ".join(loc_parts) if loc_parts else "India"

            listings.append(JobListing(
                jobid=str(job_id),
                role_name=title,
                job_listing_link=job_link,
                location=location
            ))

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://corporate.target.com/careers/job-search?currentPage=1&jobAreas=Target%20Tech&country=India",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        api_url = "https://corporate.target.com/api/jobsearch"
        listings = []
        seen_ids = set()
        page = 1
        max_pages = 20

        async with AsyncSession(impersonate="chrome124") as s:
            while page <= max_pages:
                data = (
                    f"currentPage={page}&q=&hierarchy=&remotetype=&jobcategories=Target%20Tech"
                    f"&workersubtype=&scheduletype=&basepayfrequency=&organization=&locationname="
                    f"&jobaddress=&profiles=&city=&state=&country=India&internshipType=&jobfamily="
                    f"&subFamilies=&culture=en-us&filtercondition=&compgrade="
                )
                logger.info(f"Fetching Target jobs page {page}: {api_url}")
                res = await s.post(api_url, data=data, headers=headers, timeout=20)
                if res.status_code != 200:
                    logger.warning(f"Target API returned status {res.status_code} on page {page}")
                    break

                try:
                    res_json = res.json()
                except Exception as je:
                    logger.error(f"Failed to parse Target JSON response on page {page}: {je}")
                    break

                total_count = res_json.get("count", 0)
                results = res_json.get("results", [])
                if not results:
                    break

                new_listings = self._parse_results(results, seen_ids)
                listings.extend(new_listings)

                if len(listings) >= total_count:
                    break

                page += 1

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Target scrape via Playwright browser session fallback...")
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

                landing_url = "https://corporate.target.com/careers/job-search?currentPage=1&jobAreas=Target%20Tech&country=India"
                try:
                    await page.goto(landing_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    logger.warning(f"Playwright navigation warning on Target landing page: {e}")

                page_num = 1
                max_pages = 20
                while page_num <= max_pages:
                    body_payload = (
                        f"currentPage={page_num}&q=&hierarchy=&remotetype=&jobcategories=Target%20Tech"
                        f"&workersubtype=&scheduletype=&basepayfrequency=&organization=&locationname="
                        f"&jobaddress=&profiles=&city=&state=&country=India&internshipType=&jobfamily="
                        f"&subFamilies=&culture=en-us&filtercondition=&compgrade="
                    )
                    data = await page.evaluate(f"""async () => {{
                        try {{
                            let res = await fetch("https://corporate.target.com/api/jobsearch", {{
                                method: "POST",
                                headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
                                body: "{body_payload}"
                            }});
                            if (!res.ok) return null;
                            return await res.json();
                        }} catch(e) {{
                            return null;
                        }}
                    }}""")

                    if not data or not isinstance(data, dict):
                        break

                    total_count = data.get("count", 0)
                    results = data.get("results", [])
                    if not results:
                        break

                    new_listings = self._parse_results(results, seen_ids)
                    listings.extend(new_listings)

                    if len(listings) >= total_count:
                        break

                    page_num += 1

            except Exception as pe:
                logger.error(f"Playwright fallback failed for Target: {pe}")
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Finished Target Careers HTTP scrape. Found {len(listings)} listings.")
                return listings
        except Exception as e:
            logger.warning(f"Target HTTP scrape failed: {e}. Trying Playwright fallback...")

        try:
            listings = await self._scrape_playwright()
            logger.info(f"Finished Target Careers Playwright fallback scrape. Found {len(listings)} listings.")
            return listings
        except Exception as e:
            logger.error(f"Error in Target portal Playwright fallback: {e}", exc_info=True)
            return []
