import logging
import re
from typing import List
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

    async def scrape(self) -> List[JobListing]:
        url = (
            "https://www.mckinsey.com/careers/search-jobs"
            "?countries=India&interest=Tech+%26+AI&interest=Technology+%26+Digital&functions=Technology"
        )
        logger.info(f"Scraping McKinsey Careers Portal from {url}...")
        
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
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ),
                    ignore_https_errors=True,
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                        "Sec-Ch-Ua-Mobile": "?0",
                        "Sec-Ch-Ua-Platform": '"macOS"',
                    }
                )
                page = await context.new_page()

                # Block images, fonts, media, and stylesheets for ultra-low RAM usage
                async def block_resources(route):
                    if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", block_resources)

                logger.info(f"Navigating to {url}")
                response = await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                if not response or response.status != 200:
                    logger.warning(f"McKinsey Careers returned status {response.status if response else 'None'}")

                await page.wait_for_timeout(3000)

                # Paginate by clicking 'Load More' if present
                max_clicks = 15
                clicks = 0
                while clicks < max_clicks:
                    load_more = page.locator('button:has-text("Load More"), a:has-text("Load More")')
                    if await load_more.count() > 0 and await load_more.first.is_visible():
                        logger.info(f"Clicking 'Load More' button (iteration {clicks + 1})...")
                        await load_more.first.click()
                        await page.wait_for_timeout(2000)
                        clicks += 1
                    else:
                        break

                elements = await page.query_selector_all('a[href*="/careers/search-jobs/jobs/"]')
                logger.info(f"Found {len(elements)} job links on McKinsey page.")

                for elem in elements:
                    href = await elem.get_attribute("href")
                    title = (await elem.inner_text()).strip()

                    if not href or not title:
                        continue

                    # Extract job_id using numeric regex at the end of slug, or fallback to url slug
                    match = re.search(r"-(\d+)(?:[/?#]|$)", href)
                    if match:
                        job_id = match.group(1)
                    else:
                        job_id = href.rstrip("/").split("/")[-1]

                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    full_url = href if href.startswith("http") else f"https://www.mckinsey.com{href}"

                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=full_url
                        )
                    )

            finally:
                await browser.close()

        logger.info(f"Finished McKinsey Careers scrape. Found total {len(listings)} listings.")
        return listings
