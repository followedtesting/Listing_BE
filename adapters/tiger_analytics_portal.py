import logging
from typing import List
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

    async def scrape(self) -> List[JobListing]:
        url = "https://www.tigeranalytics.com/about-us/current-openings/"
        logger.info(f"Navigating to Tiger Analytics Careers page: {url}")

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

                # Block images, fonts, media for ultra-low RAM usage
                async def block_resources(route):
                    if route.request.resource_type in ["image", "media", "font"]:
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", block_resources)

                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)

                # Clean up auto-opening popup modal (.pum / .pum-overlay) that intercepts pointer clicks
                await page.evaluate(
                    "() => { document.querySelectorAll('.pum-overlay, .pum').forEach(el => el.remove()); }"
                )

                # Select India tab explicitly
                india_tab = page.locator('li[data-country="india"]')
                if await india_tab.count() > 0 and await india_tab.first.is_visible():
                    logger.info("Selecting India country tab on Tiger Analytics frontend...")
                    await india_tab.first.click()
                    await page.wait_for_timeout(2000)

                page_num = 1
                max_pages = 30

                while page_num <= max_pages:
                    # Remove any popup overlay that might reappear on DOM mutation
                    await page.evaluate(
                        "() => { document.querySelectorAll('.pum-overlay, .pum').forEach(el => el.remove()); }"
                    )

                    india_container = page.locator("#india")
                    if await india_container.count() > 0:
                        rows = await india_container.locator(".all-jobs-list-wrap").all()
                    else:
                        rows = await page.locator(".all-jobs-list-wrap").all()

                    logger.info(f"Tiger Analytics Page {page_num}: Found {len(rows)} job row elements.")

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

                        # Extract ID from end of URL slug
                        # e.g., https://careers.tigeranalytics.com/#!/job-view/snowflake-dbt-architect-202608121520498
                        parts = href.split("-")
                        jobid = parts[-1].split("?")[0] if parts else href

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

                    # Locate the Next page button for India pagination (#career_in_pagination)
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
                            logger.info("Next page button is disabled or hidden. Reached last page.")
                            break

                        logger.info(f"Clicking Next page button (page {page_num + 1}, data-page={data_page})...")
                        # JS click bypasses any residual modal overlay pointer intercepts
                        await btn.evaluate("el => el.click()")
                        await page.wait_for_timeout(2000)
                        page_num += 1
                    else:
                        logger.info("No next pagination button found. Finishing pagination.")
                        break

            except Exception as e:
                logger.error(f"Failed to scrape Tiger Analytics Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()

        logger.info(f"Finished Tiger Analytics Careers scrape. Found total {len(listings)} listings across all pages.")
        return listings
