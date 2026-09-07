import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PhonePePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "phonepe_careers"

    @property
    def portal_name(self) -> str:
        return "PhonePe Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://www.phonepe.com/careers/job-openings/"
        logger.info(f"Navigating to PhonePe Careers: {target_url}")

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

                await page.goto(target_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # Fetch PhonePe job postings JSON endpoint inside browser context
                json_url = "https://www.phonepe.com/apollo/job-postings/latest.json"
                api_data = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const response = await fetch('{json_url}');
                            return await response.json();
                        }} catch (err) {{
                            return {{ "error": err.message }};
                        }}
                    }}
                """)

                if isinstance(api_data, dict) and "results" in api_data:
                    results = api_data.get("results", [])
                    logger.info(f"Retrieved {len(results)} total postings from PhonePe API.")

                    for job in results:
                        dept = str(job.get("department", "")).strip()
                        apply_url = job.get("applyUrl")
                        title = str(job.get("title", "")).strip()

                        if dept.lower() == "engineering" and apply_url and title:
                            apply_url_str = str(apply_url).strip()
                            parts = apply_url_str.rstrip("/").split("/")
                            job_id = parts[-1] if parts else apply_url_str

                            if job_id and job_id not in seen_ids:
                                seen_ids.add(job_id)
                                listings.append(
                                    JobListing(
                                        jobid=job_id,
                                        role_name=title,
                                        job_listing_link=apply_url_str
                                    )
                                )

                    logger.info(f"PhonePe API matched {len(listings)} Engineering jobs.")

                # Fallback to DOM interaction and parsing if API returned zero jobs
                if not listings:
                    logger.info("Fallback to DOM interaction on PhonePe Careers page...")
                    elements = await page.query_selector_all("text='Engineering'")
                    for el in elements:
                        if await el.is_visible():
                            await el.click(force=True)
                            await page.wait_for_timeout(2000)
                            break

                    smart_anchors = await page.query_selector_all("a[href*='smartrecruiters']")
                    for a in smart_anchors:
                        href = await a.get_attribute("href")
                        if not href:
                            continue

                        parts = href.rstrip("/").split("/")
                        job_id = parts[-1] if parts else ""

                        if not job_id or job_id in seen_ids:
                            continue

                        text = await a.inner_text()
                        lines = [line.strip() for line in text.split("\n") if line.strip()]
                        # In PhonePe job card, title is typically line index 2 or last non-location line
                        title = ""
                        for line in lines:
                            if line not in ["Pune", "Bengaluru", "Engineering", "Full-time"] and not line.endswith("ago"):
                                title = line
                                break
                        if not title and lines:
                            title = lines[0]

                        if job_id and title:
                            seen_ids.add(job_id)
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=href
                                )
                            )

            except Exception as e:
                logger.error(f"Failed to scrape PhonePe Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()

        logger.info(f"Finished PhonePe Careers scrape. Found total {len(listings)} listings.")
        return listings
