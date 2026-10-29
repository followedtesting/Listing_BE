import asyncio
import gc
import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class StandardCharteredPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "standard_chartered_careers"

    @property
    def portal_name(self) -> str:
        return "Standard Chartered Careers Portal"

    async def scrape(self) -> List[JobListing]:
        facet_filters = "%7B%22cust_region%22%3A%5B%22Asia%22%5D%2C%22jobLocationCountry%22%3A%5B%22India%22%5D%2C%22mfield1%22%3A%5B%22Technology%22%5D%7D"
        logger.info("Starting Standard Chartered Careers scrape...")

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
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,mp4,webm}",
                lambda route: route.abort()
            )

            page_num = 0
            max_pages = 25

            while page_num < max_pages:
                url = (
                    f"https://jobs.standardchartered.com/go/Experienced-Professional-jobs/9783657/"
                    f"?markerViewed=&carouselIndex=&facetFilters={facet_filters}&pageNumber={page_num}&sortBy=date"
                )
                logger.info(f"Loading Standard Chartered pageNumber {page_num}: {url}")

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception as nav_err:
                    logger.warning(f"Non-fatal navigation warning on pageNumber {page_num}: {nav_err}")

                try:
                    await page.wait_for_selector("a[href*='/job/']", timeout=8000)
                except Exception:
                    # No job links appeared on this page
                    break

                links = await page.query_selector_all("a")
                page_listings_count = 0
                duplicate_found = False

                for link in links:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()

                    if href and "/job/" in href.lower():
                        parts = href.strip().split("/")
                        last_seg = parts[-1]
                        jobid = ""
                        if "-" in last_seg:
                            jobid_part = last_seg.split("-")[0]
                            if jobid_part.isdigit():
                                jobid = jobid_part

                        title_clean = title.strip().replace("\n", " ")

                        if jobid and title_clean:
                            if jobid in seen_ids:
                                duplicate_found = True
                                break

                            seen_ids.add(jobid)
                            page_listings_count += 1
                            full_link = href.strip() if href.startswith("http") else f"https://jobs.standardchartered.com{href.strip()}"

                            listings.append(
                                JobListing(
                                    jobid=jobid.strip(),
                                    role_name=title_clean,
                                    job_listing_link=full_link,
                                    location="India",
                                )
                            )

                if duplicate_found or page_listings_count == 0:
                    break

                page_num += 1

        except Exception as e:
            logger.error(f"Failed to scrape Standard Chartered Careers Portal: {e}", exc_info=True)
            raise
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

        logger.info(f"Finished Standard Chartered Careers scrape. Found total {len(listings)} listings.")
        return listings
