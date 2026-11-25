import asyncio
import gc
import logging
from typing import List, Set
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

BASE_SEARCH_URL = "https://jobs.apple.com/en-in/search"
SEARCH_QUERY = (
    "sort=newest&location=india-INDC&team="
    "ai-and-machine-learning-data-operations-MLAI-AIMLDO+"
    "computer-vision-MLAI-CV+"
    "data-science-engineering-and-generation-MLAI-DSEG+"
    "deep-learning-generative-ai-and-foundation-models-MLAI-DLRL+"
    "engineering-project-and-programme-management-MLAI-EPPM+"
    "information-systems-and-technology-MLAI-IST+"
    "machine-learning-compute-and-infrastructure-MLAI-MLI+"
    "mapping-and-motion-MLAI-MM+"
    "natural-language-processing-and-speech-technologies-MLAI-NLP+"
    "privacy-MLAI-PRI+"
    "responsible-ai-and-safety-MLAI-RAIS+"
    "search-and-knowledge-MLAI-SK+"
    "security-MLAI-SEC+"
    "apps-and-frameworks-SFTWR-AF+"
    "camera-and-photos-SFTWR-CP+"
    "cloud-and-back-end-infrastructure-SFTWR-CLD+"
    "devops-and-site-reliability-SFTWR-DSR+"
    "engineering-project-and-programme-management-SFTWR-EPM+"
    "gpu-and-graphics-SFTWR-GPUG+"
    "information-systems-and-technology-SFTWR-ISTECH+"
    "machine-learning-and-ai-SFTWR-MCHLN+"
    "operating-systems-SFTWR-COS+"
    "product-design-SFTWR-PD+"
    "security-and-privacy-SFTWR-SEC+"
    "software-quality-automation-tools-and-validation-SFTWR-SQAT+"
    "spatial-computing-SFTWR-SC+"
    "trust-and-safety-SFTWR-TS+"
    "user-experience-engineering-SFTWR-UEE+"
    "video-media-and-audio-technologies-SFTWR-VMAT+"
    "wireless-software-SFTWR-WSFT"
)


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

            if not title or title.lower() in ("see full role description", "where we're hiring", "where we’re hiring"):
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

                # Extract location from card row if available
                location = "India"
                row = link.find_parent("div", class_="job-list-item")
                if row:
                    loc_div = row.select_one(".job-title-location")
                    if loc_div:
                        store_name = loc_div.select_one("[id*='store-name']")
                        if store_name and store_name.get_text(strip=True):
                            city = store_name.get_text(strip=True)
                            location = f"{city}, India" if "india" not in city.lower() else city
                        else:
                            copy_div = BeautifulSoup(str(loc_div), "html.parser")
                            for bad in copy_div.select(".a11y, .visuallyhidden"):
                                bad.decompose()
                            raw = copy_div.get_text(strip=True)
                            if raw:
                                location = f"{raw}, India" if "india" not in raw.lower() else raw

                listings.append(
                    JobListing(
                        jobid=jobid.strip(),
                        role_name=title,
                        job_listing_link=full_link,
                        location=location,
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

        async with AsyncSession(impersonate="chrome124") as s:
            page_num = 1
            max_pages = 25
            while page_num <= max_pages:
                url = f"{BASE_SEARCH_URL}?{SEARCH_QUERY}&page={page_num}"
                resp = await s.get(url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    logger.warning(f"Apple returned status {resp.status_code} on page {page_num}")
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup
                if added == 0:
                    break
                page_num += 1

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Scraping Apple Careers page via Playwright fallback...")

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
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            page = await context.new_page()

            # Abort heavy assets
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort(),
            )

            page_num = 1
            max_pages = 25

            while page_num <= max_pages:
                page_url = f"{BASE_SEARCH_URL}?{SEARCH_QUERY}&page={page_num}"
                await page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2000)

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                added = self._extract_from_soup(soup, seen_ids, listings)
                del soup
                if added == 0:
                    break
                page_num += 1

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
