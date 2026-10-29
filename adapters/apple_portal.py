import asyncio
import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ApplePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "apple_careers"

    @property
    def portal_name(self) -> str:
        return "Apple Careers Portal"

    def _extract_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str], listings: List[JobListing]) -> int:
        links = soup.select("a[href*='/details/']")
        added = 0
        for link in links:
            href = (link.get("href") or "").strip()
            title = link.get_text(strip=True)

            if not title or title.lower() == "see full role description":
                continue

            parts = href.split("/")
            jobid = ""
            try:
                details_idx = parts.index("details")
                if details_idx + 1 < len(parts):
                    jobid = parts[details_idx + 1]
            except ValueError:
                pass

            if jobid and title and jobid not in seen_ids:
                seen_ids.add(jobid)
                added += 1
                full_link = href if href.startswith("http") else f"https://jobs.apple.com{href}"
                listings.append(
                    JobListing(
                        jobid=jobid.strip(),
                        role_name=title,
                        job_listing_link=full_link,
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
            page_num = 1
            max_pages = 10
            while page_num <= max_pages:
                url = (
                    f"https://jobs.apple.com/en-in/search?"
                    f"location=india-INDC&team=apps-and-frameworks-SFTWR-AF+machine-learning-SFTWR-MCHLN+core-operating-systems-SFTWR-COS"
                    f"&page={page_num}"
                )
                resp = await s.get(url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup
                if added == 0:
                    break
                page_num += 1

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        url = "https://jobs.apple.com/en-in/search?location=india-INDC&team=apps-and-frameworks-SFTWR-AF+machine-learning-SFTWR-MCHLN+core-operating-systems-SFTWR-COS"
        logger.info(f"Navigating to Apple Careers page via Playwright fallback: {url}")

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
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            page = await context.new_page()

            # Abort heavy assets
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort()
            )

            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(4000)

            page_num = 1
            max_pages = 10

            while page_num <= max_pages:
                links = await page.query_selector_all("a")
                page_listings_count = 0
                duplicate_found = False

                for link in links:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()

                    if href and "/details/" in href.lower():
                        title_clean = title.strip()
                        if not title_clean or title_clean.lower() == "see full role description":
                            continue

                        parts = href.strip().split("/")
                        jobid = ""
                        try:
                            details_idx = parts.index("details")
                            if details_idx + 1 < len(parts):
                                jobid = parts[details_idx + 1]
                        except ValueError:
                            pass

                        if jobid and title_clean:
                            if jobid in seen_ids:
                                duplicate_found = True
                                break

                            seen_ids.add(jobid)
                            page_listings_count += 1
                            job_listing_link = href.strip() if href.startswith("http") else f"https://jobs.apple.com{href.strip()}"

                            listings.append(
                                JobListing(
                                    jobid=jobid.strip(),
                                    role_name=title_clean,
                                    job_listing_link=job_listing_link,
                                    location="India",
                                )
                            )

                if duplicate_found:
                    break

                next_button = await page.query_selector("button:has-text('Next Page'), button[aria-label='Next Page'], button.icon-chevronend")
                if next_button and await next_button.is_visible():
                    is_disabled = await page.evaluate("""
                        (btn) => {
                            if (btn.disabled || btn.classList.contains('disabled') || btn.getAttribute('aria-disabled') === 'true') {
                                return true;
                            }
                            const parent = btn.closest('li');
                            if (parent && (parent.classList.contains('disabled') || parent.classList.contains('pagination-disabled'))) {
                                return true;
                            }
                            return false;
                        }
                    """, next_button)

                    if is_disabled:
                        break
                    else:
                        await next_button.click()
                        await page.wait_for_timeout(4000)
                        page_num += 1
                else:
                    break

        except Exception as e:
            logger.error(f"Playwright fallback failed for Apple: {e}")
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
                logger.info(f"Apple curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"Apple curl scrape failed: {e}. Falling back to Playwright...")

        listings = await self._scrape_playwright()
        logger.info(f"Apple Playwright scraped {len(listings)} jobs.")
        return listings
