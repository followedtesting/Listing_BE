import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NetAppPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "netapp_careers"

    @property
    def portal_name(self) -> str:
        return "NetApp Careers"

    def _extract_from_html(self, html: str, seen_ids: Set[str], listings: List[JobListing]) -> int:
        india_cities = ["bengaluru", "bangalore", "mumbai", "chennai", "delhi", "hyderabad", "noida", "pune", "india"]
        soup = BeautifulSoup(html, "html.parser")
        anchors = soup.select("section#search-results a[href*='/job/'], ul a[href*='/job/'], a[href*='/job/']")
        page_added = 0
        for a in anchors:
            href = (a.get("href") or "").strip()
            text = a.get_text() or ""
            title = text.strip().replace("\n", " ")
            title_lower = title.lower()
            href_lower = href.lower()

            is_india = "india" in title_lower or any(c in title_lower or f"/job/{c}/" in href_lower for c in india_cities)
            if not is_india:
                continue

            parts = [p for p in href.rstrip("/").split("/") if p]
            job_id = None
            if len(parts) >= 2 and parts[-1].isdigit():
                job_id = parts[-1]
            elif len(parts) >= 3 and parts[-2].isdigit():
                job_id = parts[-2]
            else:
                job_id = href

            if job_id and title and job_id not in seen_ids:
                seen_ids.add(job_id)
                full_link = href if href.startswith("http") else f"https://careers.netapp.com{href}"
                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=full_link,
                        location="India",
                    )
                )
                page_added += 1
        del soup
        return page_added

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        async with AsyncSession(impersonate="chrome120") as s:
            page_num = 1
            while page_num <= 15:
                seo_url = f"https://careers.netapp.com/search-jobs/India/27600/{page_num}"
                resp = await s.get(seo_url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    break
                added = self._extract_from_html(resp.text, seen_ids, listings)
                if added == 0:
                    break
                page_num += 1
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        playwright_obj = None
        browser = None
        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                    "--disable-extensions",
                    "--js-flags=--max-old-space-size=128",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort()
            )

            page_num = 1
            while page_num <= 15:
                seo_url = f"https://careers.netapp.com/search-jobs/India/27600/{page_num}"
                await page.goto(seo_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1500)
                html = await page.content()
                added = self._extract_from_html(html, seen_ids, listings)
                if added == 0:
                    break
                page_num += 1
        except Exception as e:
            logger.error(f"Playwright fallback failed for NetApp: {e}")
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
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"NetApp curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"NetApp curl scrape failed: {e}. Falling back to Playwright...")
        
        listings = await self._scrape_playwright()
        logger.info(f"NetApp Playwright scraped {len(listings)} jobs.")
        return listings
