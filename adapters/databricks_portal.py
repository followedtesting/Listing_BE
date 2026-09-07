import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class DatabricksPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "databricks_careers"

    @property
    def portal_name(self) -> str:
        return "Databricks Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://www.databricks.com/company/careers/open-positions?department=Engineering&location=India"
        logger.info(f"Navigating to Databricks Careers: {target_url}")

        listings: List[JobListing] = []
        seen_ids = set()
        india_cities = ["india", "bengaluru", "bangalore", "gurgaon", "gurugram", "noida", "hyderabad", "mumbai", "pune", "delhi"]

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

                # Fetch Greenhouse public board REST API inside page context
                api_url = "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true"
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

                if isinstance(api_data, dict) and "jobs" in api_data:
                    jobs = api_data.get("jobs", [])
                    logger.info(f"Retrieved {len(jobs)} total jobs from Databricks Greenhouse API.")

                    for job in jobs:
                        job_id = str(job.get("id", "")).strip()
                        title = str(job.get("title", "")).strip()
                        loc_name = job.get("location", {}).get("name", "").strip()
                        depts = [d.get("name", "").strip() for d in job.get("departments", [])]

                        # Check India location
                        is_india = any(city in loc_name.lower() for city in india_cities)

                        # Engineering department rule: contains 'engineering' but NOT 'field engineering'
                        is_eng = any("engineering" in d.lower() and "field engineering" not in d.lower() for d in depts)

                        if is_india and is_eng and job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            job_link = f"https://www.databricks.com/company/careers/open-positions/job?gh_jid={job_id}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=job_link
                                )
                            )

                    logger.info(f"Databricks Greenhouse API matched {len(listings)} Engineering jobs in India.")

                # Fallback to DOM parsing if API returned zero jobs
                if not listings:
                    logger.info("Fallback to DOM parsing on Databricks Careers page...")
                    job_anchors = await page.query_selector_all("a[href*='/company/careers/']")
                    for a in job_anchors:
                        href = await a.get_attribute("href")
                        if not href or not ("-" in href or "gh_jid" in href):
                            continue

                        # Extract job id if present in URL
                        job_id = ""
                        if "gh_jid=" in href:
                            job_id = href.split("gh_jid=")[-1].split("&")[0]
                        else:
                            parts = href.split("?")[0].rstrip("/").split("-")
                            if parts and parts[-1].isdigit():
                                job_id = parts[-1]

                        if not job_id or job_id in seen_ids:
                            continue

                        text = await a.inner_text()
                        lines = [line.strip() for line in text.split("\n") if line.strip()]
                        title = lines[0] if lines else ""

                        if job_id and title:
                            seen_ids.add(job_id)
                            full_link = href if href.startswith("http") else f"https://www.databricks.com{href}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )

            except Exception as e:
                logger.error(f"Failed to scrape Databricks Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()

        logger.info(f"Finished Databricks Careers scrape. Found total {len(listings)} listings.")
        return listings
