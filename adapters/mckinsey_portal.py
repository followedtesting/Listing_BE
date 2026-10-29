import asyncio
import gc
import logging
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class McKinseyPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "mckinsey_careers"

    @property
    def portal_name(self) -> str:
        return "McKinsey Careers Portal"

    async def _scrape_curl(self) -> List[JobListing]:
        url = "https://gateway.mckinsey.com/apigw-x0cceuow60/v1/api/jobs/search"
        params = {
            "countries": "India",
            "interest": "Tech & AI",
            "functions": "Technology",
            "pageSize": "50",
            "start": "0",
            "lang": "en",
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.mckinsey.com",
            "Referer": "https://www.mckinsey.com/careers/search-jobs",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with AsyncSession(impersonate="chrome120") as s:
            start = 0
            page_size = 50
            while True:
                params["start"] = str(start)
                resp = await s.get(url, params=params, headers=headers, timeout=25)
                if resp.status_code != 200:
                    break

                try:
                    data = resp.json()
                except Exception:
                    break

                docs = data.get("docs", [])
                if not docs:
                    break

                for doc in docs:
                    job_id = str(doc.get("jobID") or "").strip()
                    title = (doc.get("title") or "").strip()
                    friendly_url = doc.get("friendlyURL") or job_id
                    cities = doc.get("cities") or ["India"]
                    loc = ", ".join(cities) if isinstance(cities, list) else str(cities)

                    if job_id and title and job_id not in seen_ids:
                        seen_ids.add(job_id)
                        link = f"https://www.mckinsey.com/careers/search-jobs/jobs/{friendly_url}"
                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=link,
                                location=loc,
                            )
                        )

                num_found = data.get("numFound", 0)
                start += len(docs)
                if start >= num_found or len(docs) < page_size:
                    break

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        url = (
            "https://www.mckinsey.com/careers/search-jobs"
            "?countries=India&interest=Tech+%26+AI&interest=Technology+%26+Digital&functions=Technology"
        )
        logger.info(f"Scraping McKinsey Careers Portal via Playwright fallback from {url}...")

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

            # Abort images, fonts, media
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,mp4,webm}",
                lambda route: route.abort()
            )

            await page.goto(url, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            max_clicks = 15
            clicks = 0
            while clicks < max_clicks:
                load_more = page.locator('button:has-text("Load More"), a:has-text("Load More")')
                if await load_more.count() > 0 and await load_more.first.is_visible():
                    await load_more.first.click()
                    await page.wait_for_timeout(2000)
                    clicks += 1
                else:
                    break

            elements = await page.query_selector_all('a[href*="/careers/search-jobs/jobs/"]')
            for elem in elements:
                href = await elem.get_attribute("href")
                title = (await elem.inner_text()).strip()

                if not href or not title:
                    continue

                match = re.search(r"-(\d+)(?:[/?#]|$)", href)
                job_id = match.group(1) if match else href.rstrip("/").split("/")[-1]

                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                full_url = href if href.startswith("http") else f"https://www.mckinsey.com{href}"
                listings.append(
                    JobListing(
                        jobid=job_id,
                        role_name=title,
                        job_listing_link=full_url,
                        location="India",
                    )
                )

        except Exception as e:
            logger.error(f"Playwright fallback failed for McKinsey: {e}")
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
                logger.info(f"McKinsey curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"McKinsey curl scrape failed: {e}. Falling back to Playwright...")

        listings = await self._scrape_playwright()
        logger.info(f"McKinsey Playwright scraped {len(listings)} jobs.")
        return listings
