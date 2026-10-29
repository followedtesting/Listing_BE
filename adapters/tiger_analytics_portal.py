import asyncio
import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class TigerAnalyticsPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "tiger_analytics_careers"

    @property
    def portal_name(self) -> str:
        return "Tiger Analytics Careers Portal"

    def _extract_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str], listings: List[JobListing]) -> int:
        rows = soup.select(".all-jobs-list-wrap")
        added = 0
        for row in rows:
            title_elem = row.select_one(".jobs-title")
            link_elem = row.select_one(".jobs-apply a")
            if not title_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True)
            href = (link_elem.get("href") or "").strip()
            if not title or not href:
                continue

            parts = href.split("-")
            jobid = parts[-1].split("?")[0] if parts else href
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
            "Accept": "text/html, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.tigeranalytics.com",
            "Referer": "https://www.tigeranalytics.com/about-us/current-openings/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
        }

        async with AsyncSession(impersonate="chrome120") as s:
            page_num = 1
            max_pages = 30
            while page_num <= max_pages:
                data = {
                    "action": "get_tiger_india_jobs",
                    "page": str(page_num),
                    "title": "",
                }
                resp = await s.post(
                    "https://www.tigeranalytics.com/wp-admin/admin-ajax.php",
                    data=data,
                    headers=headers,
                    timeout=25,
                )
                if resp.status_code != 200 or not resp.text.strip():
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup
                if added == 0:
                    break
                page_num += 1

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        url = "https://www.tigeranalytics.com/about-us/current-openings/"
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

            # Abort heavy assets
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,mp4,webm}",
                lambda route: route.abort()
            )

            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)

            await page.evaluate(
                "() => { document.querySelectorAll('.pum-overlay, .pum').forEach(el => el.remove()); }"
            )

            india_tab = page.locator('li[data-country="india"]')
            if await india_tab.count() > 0 and await india_tab.first.is_visible():
                await india_tab.first.click()
                await page.wait_for_timeout(1500)

            page_num = 1
            max_pages = 30

            while page_num <= max_pages:
                await page.evaluate(
                    "() => { document.querySelectorAll('.pum-overlay, .pum').forEach(el => el.remove()); }"
                )

                india_container = page.locator("#india")
                if await india_container.count() > 0:
                    rows = await india_container.locator(".all-jobs-list-wrap").all()
                else:
                    rows = await page.locator(".all-jobs-list-wrap").all()

                new_on_page = 0
                for row in rows:
                    if not await row.is_visible():
                        continue

                    title_elem = row.locator(".jobs-title")
                    link_elem = row.locator(".jobs-apply a")
                    if await title_elem.count() == 0 or await link_elem.count() == 0:
                        continue

                    title = (await title_elem.first.inner_text()).strip()
                    href = (await link_elem.first.get_attribute("href")).strip()
                    if not title or not href:
                        continue

                    parts = href.split("-")
                    jobid = parts[-1].split("?")[0] if parts else href

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

                next_btn = page.locator(
                    "#career_in_pagination button.career_pagination_next, "
                    "#india button.career_pagination_next, "
                    "button.career_pagination_next:visible"
                )

                if await next_btn.count() > 0:
                    btn = next_btn.first
                    is_disabled = await btn.get_attribute("disabled")
                    style = await btn.get_attribute("style")
                    data_page = await btn.get_attribute("data-page")

                    if is_disabled or (style and "none" in style) or not data_page:
                        break

                    await btn.evaluate("el => el.click()")
                    await page.wait_for_timeout(1500)
                    page_num += 1
                else:
                    break

        except Exception as e:
            logger.error(f"Playwright fallback failed for Tiger Analytics: {e}")
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
                logger.info(f"Tiger Analytics curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"Tiger Analytics curl scrape failed: {e}. Falling back to Playwright...")

        listings = await self._scrape_playwright()
        logger.info(f"Tiger Analytics Playwright scraped {len(listings)} jobs.")
        return listings
