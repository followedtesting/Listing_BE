import logging
from typing import List
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

    async def scrape(self) -> List[JobListing]:
        url = (
            "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/Software%20Engineer"
            "?42386=%5B812053%5D&42386_format=17546&42390=%5B102156%5D&42390_format=17550"
            "&listFilterMode=1&folderRecordsPerPage=6&"
        )
        logger.info(f"Navigating to Siemens Careers page: {url}")

        listings: List[JobListing] = []
        seen_ids = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                ]
            )
            try:
                user_agent = (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()

                # Block images, fonts, media for RAM efficiency
                async def block_resources(route):
                    if route.request.resource_type in ["image", "media", "font"]:
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", block_resources)

                current_url = url
                await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)

                page_num = 1
                max_pages = 30

                while page_num <= max_pages:
                    articles = await page.locator(".article--result").all()
                    logger.info(f"Siemens Page {page_num}: Found {len(articles)} job article elements.")

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

                        # Extract Job ID from URL slug: e.g. JobDetail/522234
                        jobid = href.rstrip("/").split("/")[-1].split("?")[0]

                        if jobid and jobid not in seen_ids:
                            seen_ids.add(jobid)
                            new_on_page += 1
                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title,
                                    job_listing_link=href
                                )
                            )

                    logger.info(f"Page {page_num}: Added {new_on_page} new listings (Total cumulative: {len(listings)}).")

                    # Locate Next page link and follow href directly
                    next_link = page.locator("a[aria-label*='Next'], a:has-text('Next >>')")
                    if await next_link.count() > 0 and await next_link.first.is_visible():
                        next_href = await next_link.first.get_attribute("href")
                        if next_href:
                            if not next_href.startswith("http"):
                                next_href = f"https://jobs.siemens.com{next_href}"
                            logger.info(f"Navigating to Siemens Page {page_num + 1} -> {next_href}...")
                            await page.goto(next_href, wait_until="domcontentloaded", timeout=60000)
                            await page.wait_for_timeout(2500)
                            page_num += 1
                        else:
                            break
                    else:
                        logger.info("No next page link found. Reached final page.")
                        break

            except Exception as e:
                logger.error(f"Failed to scrape Siemens Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()

        logger.info(f"Finished Siemens Careers scrape. Total {len(listings)} listings fetched.")
        return listings
