import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PaytmPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "paytm_careers"

    @property
    def portal_name(self) -> str:
        return "Paytm Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://jobs.lever.co/paytm?department=Technology"
        logger.info(f"Navigating to Paytm Careers: {target_url}")

        listings: List[JobListing] = []
        seen_ids = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()

                await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)

                # Fetch Lever public REST API inside page context
                api_url = "https://api.lever.co/v0/postings/paytm?mode=json"
                api_data = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const response = await fetch('{api_url}');
                            return await response.json();
                        }} catch (err) {{
                            return {{ "error": err.message }};
                        }}
                    }}
                """)

                if isinstance(api_data, list):
                    logger.info(f"Retrieved {len(api_data)} total postings from Paytm Lever API.")

                    for posting in api_data:
                        posting_id = str(posting.get("id", "")).strip()
                        title = str(posting.get("text", "")).strip()
                        url = str(posting.get("hostedUrl", "")).strip()
                        categories = posting.get("categories", {})
                        dept = str(categories.get("department", "")).strip()

                        # Filter by department Technology
                        if ("technology" in dept.lower()) and posting_id and title and url and posting_id not in seen_ids:
                            seen_ids.add(posting_id)
                            listings.append(
                                JobListing(
                                    jobid=posting_id,
                                    role_name=title,
                                    job_listing_link=url
                                )
                            )

                    logger.info(f"Paytm Lever API matched {len(listings)} Technology jobs.")

                # Fallback to DOM parsing if API returned zero jobs
                if not listings:
                    logger.info("Fallback to DOM parsing on Paytm Lever page...")
                    posting_elements = await page.query_selector_all(".posting")
                    for elem in posting_elements:
                        link_elem = await elem.query_selector("a")
                        title_elem = await elem.query_selector("h5") or link_elem
                        
                        if not link_elem:
                            continue

                        href = await link_elem.get_attribute("href")
                        if not href:
                            continue

                        parts = href.rstrip("/").split("/")
                        posting_id = parts[-1] if parts else ""

                        if not posting_id or posting_id in seen_ids:
                            continue

                        title = (await title_elem.inner_text()).strip() if title_elem else ""

                        if posting_id and title:
                            seen_ids.add(posting_id)
                            listings.append(
                                JobListing(
                                    jobid=posting_id,
                                    role_name=title,
                                    job_listing_link=href
                                )
                            )

            except Exception as e:
                logger.error(f"Failed to scrape Paytm Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()

        logger.info(f"Finished Paytm Careers scrape. Found total {len(listings)} listings.")
        return listings
