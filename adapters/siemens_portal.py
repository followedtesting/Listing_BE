import asyncio
import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SiemensPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "siemens_careers"

    @property
    def portal_name(self) -> str:
        return "Siemens Careers Portal"

    def _extract_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str], listings: List[JobListing]) -> int:
        articles = soup.select(".article--result")
        added = 0
        for art in articles:
            link_elem = art.select_one("a[href*='JobDetail']")
            if not link_elem:
                continue

            title = link_elem.get_text(strip=True)
            href = (link_elem.get("href") or "").strip()
            if not title or not href:
                continue

            if not href.startswith("http"):
                href = f"https://jobs.siemens.com{href}"

            jobid = href.rstrip("/").split("/")[-1].split("?")[0]
            if jobid and jobid not in seen_ids:
                seen_ids.add(jobid)
                added += 1
                listings.append(
                    JobListing(
                        jobid=jobid,
                        role_name=title,
                        job_listing_link=href,
                        location="India",
                    )
                )
        return added

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        async with AsyncSession(impersonate="chrome120") as s:
            offset = 0
            page_size = 50
            max_offset = 500
            while offset <= max_offset:
                url = (
                    f"https://jobs.siemens.com/en_US/externaljobs/SearchJobs/Software%20Engineer/?"
                    f"42386=%5B812053%5D&42386_format=17546&42390=%5B102156%5D&42390_format=17550"
                    f"&listFilterMode=1&folderRecordsPerPage={page_size}&folderOffset={offset}"
                )
                resp = await s.get(url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup
                if added == 0:
                    break
                offset += page_size

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        url = (
            "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/Software%20Engineer"
            "?42386=%5B812053%5D&42386_format=17546&42390=%5B102156%5D&42390_format=17550"
            "&listFilterMode=1&folderRecordsPerPage=6&"
        )
        logger.info(f"Navigating to Siemens Careers page via Playwright: {url}")

        listings: List[JobListing] = []
        seen_ids = set()
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

            # Block heavy assets
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort()
            )

            current_url = url
            await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)

            page_num = 1
            max_pages = 30

            while page_num <= max_pages:
                articles = await page.locator(".article--result").all()
                new_on_page = 0
                for art in articles:
                    if not await art.is_visible():
                        continue

                    link_elem = art.locator("a[href*='JobDetail']")
                    if await link_elem.count() == 0:
                        continue

                    title = (await link_elem.first.inner_text()).strip()
                    href = (await link_elem.first.get_attribute("href")).strip()

                    if not title or not href:
                        continue

                    if not href.startswith("http"):
                        href = f"https://jobs.siemens.com{href}"

                    jobid = href.rstrip("/").split("/")[-1].split("?")[0]

                    if jobid and jobid not in seen_ids:
                        seen_ids.add(jobid)
                        new_on_page += 1
                        listings.append(
                            JobListing(
                                jobid=jobid,
                                role_name=title,
                                job_listing_link=href,
                                location="India",
                            )
                        )

                next_link = page.locator("a[aria-label*='Next'], a:has-text('Next >>')")
                if await next_link.count() > 0 and await next_link.first.is_visible():
                    next_href = await next_link.first.get_attribute("href")
                    if next_href:
                        if not next_href.startswith("http"):
                            next_href = f"https://jobs.siemens.com{next_href}"
                        await page.goto(next_href, wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(2000)
                        page_num += 1
                    else:
                        break
                else:
                    break

        except Exception as e:
            logger.error(f"Playwright fallback failed for Siemens: {e}")
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
                logger.info(f"Siemens curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"Siemens curl scrape failed: {e}. Falling back to Playwright...")

        listings = await self._scrape_playwright()
        logger.info(f"Siemens Playwright scraped {len(listings)} jobs.")
        return listings
