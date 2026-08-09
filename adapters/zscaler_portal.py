import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ZscalerPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "zscaler_careers"

    @property
    def portal_name(self) -> str:
        return "Zscaler Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://www.zscaler.com/careers/search?departments=Agentic+AI&departments=Emerging+Tech&departments=Engineering&page=1&locations=India"
        logger.info(f"Navigating to Zscaler Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        target_departments = {"agentic ai", "emerging tech", "engineering"}
        india_cities = ["india", "bangalore", "bengaluru", "hyderabad", "mohali", "pune", "delhi", "mumbai", "gurgaon"]
        
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
                
                # Fetch Zscaler internal API endpoint
                api_data = await page.evaluate("""
                    async () => {
                        try {
                            const response = await fetch('/api/get-greenhouse-jobs');
                            return await response.json();
                        } catch (err) {
                            return { "error": err.message };
                        }
                    }
                """)
                
                if isinstance(api_data, dict) and "error" not in api_data:
                    jobs = api_data.get("jobs", [])
                    logger.info(f"Retrieved {len(jobs)} total jobs from Zscaler internal API.")
                    
                    for job in jobs:
                        job_id = str(job.get("id", "")).strip()
                        title = str(job.get("title", "")).strip()
                        url = str(job.get("absolute_url", "")).strip()
                        
                        if not job_id or not title or not url or job_id in seen_ids:
                            continue
                            
                        # Extract department names/labels
                        depts = job.get("departments", [])
                        dept_names = set()
                        for d in depts:
                            if isinstance(d, dict):
                                lbl = (d.get("label") or d.get("name") or d.get("value") or "").strip().lower()
                                if lbl:
                                    dept_names.add(lbl)
                            elif isinstance(d, str):
                                dept_names.add(d.strip().lower())
                                
                        div = job.get("division")
                        if isinstance(div, dict) and div.get("label"):
                            dept_names.add(div["label"].strip().lower())
                            
                        # Extract location info
                        locations = job.get("locations", [])
                        is_india = False
                        for loc in locations:
                            if isinstance(loc, dict):
                                c_name = (loc.get("country") or "").strip().lower()
                                l_name = (loc.get("location") or "").strip().lower()
                                if c_name == "india" or any(city in l_name for city in india_cities):
                                    is_india = True
                                    break
                            elif isinstance(loc, str):
                                l_name = loc.strip().lower()
                                if any(city in l_name for city in india_cities):
                                    is_india = True
                                    break
                                    
                        dept_match = bool(dept_names & target_departments)
                        
                        if is_india and dept_match:
                            seen_ids.add(job_id)
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=url
                                )
                            )
                            
            except Exception as e:
                logger.error(f"Failed to scrape Zscaler Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Zscaler Careers scrape. Found total {len(listings)} listings.")
        return listings
