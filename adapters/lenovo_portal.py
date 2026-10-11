import logging
import asyncio
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class LenovoPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "lenovo_careers"

    @property
    def portal_name(self) -> str:
        return "Lenovo Careers Portal"

    def _extract_listings_from_soup(self, soup: BeautifulSoup, seen_ids: Set[str]) -> List[JobListing]:
        listings = []
        articles = soup.find_all(class_=lambda c: c and "article--result" in c)

        for art in articles:
            link_elem = art.find("a", href=lambda h: h and "JobDetail" in h)
            if not link_elem:
                continue

            title = link_elem.get_text(strip=True)
            href = link_elem.get("href", "").strip()

            if not title or not href:
                continue

            if not href.startswith("http"):
                href = f"https://jobs.lenovo.com{href}"

            # Extract job ID from URL slug (e.g. /JobDetail/Forward-Deployed-Engineer/81920)
            job_id = href.rstrip("/").split("/")[-1].split("?")[0]

            # Extract location from subtitle
            loc = "India"
            subtitle = art.find(class_=lambda c: c and "article__header__text__subtitle" in c)
            if subtitle:
                spans = [s.get_text(strip=True) for s in subtitle.find_all("span")]
                for s in spans:
                    if "Req #:" not in s and "Posted" not in s and s:
                        loc = s
                        break

            if not job_id or job_id in seen_ids:
                continue

            seen_ids.add(job_id)
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=href,
                    location=loc
                )
            )

        return listings

    async def _scrape_curl(self) -> List[JobListing]:
        base_url = (
            "https://jobs.lenovo.com/en_US/careers/SearchJobs/"
            "?13036=%5B12016672%5D&13036_format=6621&1637=%5B2020737%2C326205%5D"
            "&1637_format=966&listFilterMode=1&jobRecordsPerPage=10&"
        )
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        current_url = base_url
        page_num = 1
        max_pages = 20

        async with AsyncSession(impersonate="chrome124") as session:
            while current_url and page_num <= max_pages:
                resp = await session.get(current_url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    logger.warning(f"Lenovo careers returned HTTP {resp.status_code} on page {page_num}")
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                page_listings = self._extract_listings_from_soup(soup, seen_ids)
                listings.extend(page_listings)

                # Check for next page link
                next_link = soup.find("a", class_=lambda c: c and "paginationNextLink" in c)
                if not next_link:
                    next_link = soup.find("a", attrs={"aria-label": lambda a: a and "Go to Next Page" in a})

                if next_link and next_link.get("href"):
                    next_href = next_link.get("href").strip()
                    if not next_href.startswith("http"):
                        next_href = f"https://jobs.lenovo.com{next_href}"
                    current_url = next_href
                    page_num += 1
                else:
                    break

        logger.info(f"Lenovo curl scraped {len(listings)} jobs across {page_num} page(s).")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Attempting Lenovo careers scraping via Playwright...")
        base_url = (
            "https://jobs.lenovo.com/en_US/careers/SearchJobs/"
            "?13036=%5B12016672%5D&13036_format=6621&1637=%5B2020737%2C326205%5D"
            "&1637_format=966&listFilterMode=1&jobRecordsPerPage=10&"
        )
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                current_url = base_url
                page_num = 1
                max_pages = 20

                while current_url and page_num <= max_pages:
                    await page.goto(current_url, wait_until="domcontentloaded", timeout=40000)
                    await asyncio.sleep(1.5)

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    page_listings = self._extract_listings_from_soup(soup, seen_ids)
                    listings.extend(page_listings)

                    next_link = await page.query_selector("a.paginationNextLink, a[aria-label*='Go to Next Page']")
                    if next_link:
                        next_href = (await next_link.get_attribute("href") or "").strip()
                        if next_href:
                            if not next_href.startswith("http"):
                                next_href = f"https://jobs.lenovo.com{next_href}"
                            current_url = next_href
                            page_num += 1
                        else:
                            break
                    else:
                        break

                logger.info(f"Lenovo Playwright scraped {len(listings)} jobs across {page_num} page(s).")
            except Exception as e:
                logger.error(f"Playwright scraping error for Lenovo: {e}", exc_info=True)
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        # 1. Fast direct HTML scraping via curl_cffi
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("Lenovo curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"Lenovo curl scraping failed: {e}. Falling back to Playwright...")

        # 2. Playwright fallback
        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"Lenovo Playwright scraping also failed: {e}")
            return []
