import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class RazorpayPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "razorpay_careers"

    @property
    def portal_name(self) -> str:
        return "Razorpay Careers (Greenhouse)"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited?departments%5B%5D=4024806005"
        logger.info(f"Navigating to Razorpay Careers (Greenhouse): {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        target_dept_id = 4024806005
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                
                await page.goto(target_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                
                # Fetch Greenhouse public board REST API inside page context
                api_url = "https://boards-api.greenhouse.io/v1/boards/razorpaysoftwareprivatelimited/jobs?content=true"
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
                    for job in jobs:
                        depts = job.get("departments", [])
                        match = False
                        for d in depts:
                            if d.get("id") == target_dept_id or d.get("parent_id") == target_dept_id:
                                match = True
                                break
                                
                        if match:
                            job_id = str(job.get("id", "")).strip()
                            title = str(job.get("title", "")).strip()
                            url = str(job.get("absolute_url", "")).strip()
                            
                            if job_id and title and url and job_id not in seen_ids:
                                seen_ids.add(job_id)
                                listings.append(
                                    JobListing(
                                        jobid=job_id,
                                        role_name=title,
                                        job_listing_link=url
                                    )
                                )
                                
                logger.info(f"Greenhouse REST API matched {len(listings)} jobs for Razorpay Engineering department {target_dept_id}.")
                
                # Fallback to DOM parsing if API returned zero jobs
                if not listings:
                    logger.info("Fallback to DOM parsing on Razorpay Greenhouse page...")
                    job_anchors = await page.query_selector_all("a[href*='/jobs/']")
                    for a in job_anchors:
                        href = await a.get_attribute("href")
                        if not href or "/jobs/" not in href:
                            continue
                            
                        parts = href.rstrip("/").split("/")
                        job_id = parts[-1] if parts else ""
                        if not job_id or job_id in seen_ids:
                            continue
                            
                        text = await a.inner_text()
                        lines = [line.strip() for line in text.split("\n") if line.strip()]
                        title = lines[0] if lines else ""
                        
                        if job_id and title:
                            seen_ids.add(job_id)
                            full_link = href if href.startswith("http") else f"https://job-boards.greenhouse.io{href}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )
                            
            except Exception as e:
                logger.error(f"Failed to scrape Razorpay Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Razorpay Careers scrape. Found total {len(listings)} listings.")
        return listings
