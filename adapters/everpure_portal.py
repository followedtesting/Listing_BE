import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class EverpurePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "everpure_careers"

    @property
    def portal_name(self) -> str:
        return "Everpure / Pure Storage Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://www.everpuredata.com/company/careers/opportunities.html#engineering&india&"
        logger.info(f"Navigating to Everpure Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        india_cities = ["bangalore", "bengaluru", "gurgaon", "mumbai", "delhi", "hyderabad", "chennai", "pune"]
        tech_keywords = [
            "software", "engineer", "developer", "architect", "data", "qa",
            "sre", "devops", "tech", "platform", "backend", "frontend",
            "firmware", "kernel", "systems", "member of technical staff", "mts"
        ]
        
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
                
                gh_url = "https://boards-api.greenhouse.io/v1/boards/purestorage/jobs?content=true"
                data = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const response = await fetch('{gh_url}');
                            return await response.json();
                        }} catch (err) {{
                            return {{ "error": err.message }};
                        }}
                    }}
                """)
                
                if not isinstance(data, dict) or "error" in data:
                    logger.error(f"Invalid response from Greenhouse API for Pure Storage / Everpure: {data}")
                    return []
                    
                jobs = data.get("jobs", [])
                logger.info(f"Retrieved {len(jobs)} total job postings from Greenhouse API for Pure Storage / Everpure.")
                
                for j in jobs:
                    title = (j.get("title") or "").strip()
                    title_lower = title.lower()
                    job_id = str(j.get("id") or "").strip()
                    link = j.get("absolute_url") or f"https://job-boards.greenhouse.io/purestorage/jobs/{job_id}"
                    
                    loc = (j.get("location", {}).get("name") or "").strip().lower()
                    departments = j.get("departments", [])
                    dept_names = [d.get("name", "").strip().lower() for d in departments]
                    
                    is_india = "india" in loc or any(c in loc for c in india_cities)
                    if not is_india:
                        continue
                        
                    is_eng = any("engineering" in d or "tech" in d for d in dept_names) or any(k in title_lower for k in tech_keywords)
                    
                    # Exclude non-engineering roles (Facilities, Sales SEs, Marketing, HR, Finance)
                    if any(d in dept_names for d in ["facilities", "sales", "marketing", "finance", "hr", "people"]):
                        if not any(k in title_lower for k in ["software", "firmware", "kernel", "systems engineer", "datapath", "developer"]):
                            is_eng = False
                            
                    if is_eng:
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=link
                                )
                            )
                            
            except Exception as e:
                logger.error(f"Failed to scrape Everpure Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Everpure Careers scrape. Found total {len(listings)} listings.")
        return listings
