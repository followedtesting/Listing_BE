import asyncio
import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class BarclaysPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "barclays_careers"

    @property
    def portal_name(self) -> str:
        return "Barclays Careers"

    def _extract_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str], listings: List[JobListing]) -> int:
        india_cities = ["/noida/", "/pune/", "/mumbai/", "/bengaluru/", "/chennai/", "/hyderabad/", "/gurgaon/", "/india/"]
        links = soup.select("a[href*='/job/']")
        page_added = 0
        for anchor in links:
            href = (anchor.get("href") or "").strip()
            if not href or "/job/" not in href:
                continue

            parts = href.rstrip("/").split("/")
            job_id = parts[-1] if parts else ""
            if not job_id or job_id in seen_ids:
                continue

            href_lower = href.lower()
            title = anchor.get_text(strip=True)
            if not title:
                continue

            is_india = any(city in href_lower for city in india_cities) or "india" in href_lower or "india" in title.lower()
            # If the facet filter for India is active, all returned jobs are India jobs
            seen_ids.add(job_id)
            full_link = f"https://search.jobs.barclays{href}" if href.startswith("/") else href

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location="India",
                )
            )
            page_added += 1
        return page_added

    async def _scrape_curl(self) -> List[JobListing]:
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://search.jobs.barclays/search-jobs",
        }

        async with AsyncSession(impersonate="chrome120") as s:
            page_num = 1
            max_pages = 25
            while page_num <= max_pages:
                url = (
                    f"https://search.jobs.barclays/search-jobs/results?"
                    f"ActiveFacetID=1269750&CurrentPage={page_num}&RecordsPerPage=50"
                    f"&Distance=50&RadiusUnitType=0&Keywords=&Location=&ShowRadius=False&IsPagination=False"
                    f"&CustomFacetName=&FacetTerm=&FacetType=0"
                    f"&FacetFilters%5B0%5D.ID=1269750&FacetFilters%5B0%5D.FacetType=2&FacetFilters%5B0%5D.Display=India&FacetFilters%5B0%5D.IsApplied=true"
                    f"&FacetFilters%5B1%5D.ID=79683&FacetFilters%5B1%5D.FacetType=1&FacetFilters%5B1%5D.Display=Development+and+Engineering&FacetFilters%5B1%5D.IsApplied=true"
                    f"&SearchResultsModuleName=Search+Results&SearchFiltersModuleName=Search+Filters&SortCriteria=0&SortDirection=0&SearchType=6&OrganizationIds=13015"
                )
                resp = await s.get(url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    break

                try:
                    data = resp.json()
                except Exception:
                    break

                html_snippet = data.get("results") or ""
                if not html_snippet:
                    break

                soup = BeautifulSoup(html_snippet, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup
                if added == 0:
                    break
                page_num += 1

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Barclays Careers scraping via Playwright fallback...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        india_cities = ["/noida/", "/pune/", "/mumbai/", "/bengaluru/", "/chennai/", "/hyderabad/", "/gurgaon/", "/india/"]
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
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort()
            )

            page_num = 1
            max_pages = 25

            while page_num <= max_pages:
                url = f"https://search.jobs.barclays/search-jobs?ac=79683&orgIds=13015&l=India&c=Development%20and%20Engineering&p={page_num}"
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1500)

                cards = await page.query_selector_all(".job-list--card .list-item, section#search-results-list li")
                if not cards:
                    break

                page_added = 0
                for card in cards:
                    anchor = await card.query_selector("a[href*='/job/']")
                    if not anchor:
                        continue

                    href = await anchor.get_attribute("href")
                    if not href or "/job/" not in href:
                        continue

                    parts = href.rstrip("/").split("/")
                    job_id = parts[-1] if parts else ""
                    if not job_id or job_id in seen_ids:
                        continue

                    card_text = (await card.inner_text()).lower()
                    href_lower = href.lower()

                    is_india = "india" in card_text or any(city in href_lower for city in india_cities)
                    if not is_india:
                        continue

                    h2 = await card.query_selector("h2, h3, .search-results-job-title")
                    title = await h2.inner_text() if h2 else await anchor.inner_text()
                    title = title.strip()
                    if not title:
                        continue

                    seen_ids.add(job_id)
                    full_link = f"https://search.jobs.barclays{href}" if href.startswith("/") else href

                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=full_link,
                            location="India",
                        )
                    )
                    page_added += 1

                if page_added == 0:
                    break

                page_num += 1

        except Exception as e:
            logger.error(f"Playwright fallback failed for Barclays: {e}")
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
                logger.info(f"Barclays curl scraped {len(listings)} jobs.")
                return listings
        except Exception as e:
            logger.warning(f"Barclays curl scrape failed: {e}. Falling back to Playwright...")

        listings = await self._scrape_playwright()
        logger.info(f"Barclays Playwright scraped {len(listings)} jobs.")
        return listings
