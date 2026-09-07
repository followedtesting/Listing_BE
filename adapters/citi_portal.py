import logging
import re
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class CitiPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "citi_careers"

    @property
    def portal_name(self) -> str:
        return "Citi Careers"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://jobs.citi.com/search-jobs"
        logger.info(f"Navigating to Citi Careers: {base_url}?k=&l=India&orgIds=287")

        listings: List[JobListing] = []
        seen_ids = set()
        india_keywords = ["india", "pune", "chennai", "mumbai", "bengaluru", "bangalore", "haryana", "gurgaon", "gurugram", "noida", "hyderabad", "delhi"]
        page_num = 1

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()

                while True:
                    url = f"{base_url}?k=&l=India&orgIds=287&p={page_num}"
                    logger.info(f"Fetching Citi Careers page {page_num}: {url}")

                    res = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if not res or res.status != 200:
                        logger.warning(f"Citi page {page_num} returned status {res.status if res else 'None'}. Ending pagination.")
                        break

                    await page.wait_for_timeout(2000)

                    job_cards = await page.evaluate("""
                        () => {
                            const items = Array.from(document.querySelectorAll("#search-results-list li, section#search-results-list li, ul.search-results-list li, #search-results li"));
                            return items.map(li => {
                                const a = li.querySelector("a[href*='/job/']");
                                const locEl = li.querySelector(".job-location, .location, span.job-location");
                                return {
                                    href: a ? a.getAttribute('href') : null,
                                    title: a ? a.innerText.trim() : null,
                                    location: locEl ? locEl.innerText.trim() : ''
                                };
                            }).filter(c => c.href && c.title);
                        }
                    """)

                    if not job_cards:
                        break

                    new_on_page = 0
                    for card in job_cards:
                        href = card["href"]
                        title = card["title"]
                        loc = card["location"]

                        match = re.search(r"/(\d+)$", href)
                        job_id = match.group(1) if match else href

                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            new_on_page += 1

                            is_india = any(k in href.lower() or k in loc.lower() or k in title.lower() for k in india_keywords)
                            if is_india:
                                full_link = href if href.startswith("http") else f"https://jobs.citi.com{href}"
                                listings.append(
                                    JobListing(
                                        jobid=job_id,
                                        role_name=title,
                                        job_listing_link=full_link
                                    )
                                )

                    if new_on_page == 0 or page_num >= 15:
                        break

                    page_num += 1

            except Exception as e:
                logger.error(f"Failed to scrape Citi Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()

        logger.info(f"Finished Citi Careers scrape. Found total {len(listings)} listings.")
        return listings
