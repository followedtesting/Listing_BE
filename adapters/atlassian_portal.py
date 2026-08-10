import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AtlassianPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "atlassian_careers"

    @property
    def portal_name(self) -> str:
        return "Atlassian Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://www.atlassian.com/company/careers/all-jobs?team=Engineering&location=India&search="
        api_endpoint = "https://www.atlassian.com/endpoint/careers/listings"
        logger.info(f"Navigating to Atlassian Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        eng_keywords = ["engineer", "software", "developer", "data", "architect", "tech", "machine learning", "ai"]
        
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
                
                data = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const response = await fetch('{api_endpoint}');
                            return await response.json();
                        }} catch (err) {{
                            return {{ "error": err.message }};
                        }}
                    }}
                """)
                
                if isinstance(data, dict) and "error" in data:
                    logger.error(f"Error fetching Atlassian jobs from API: {data}")
                    return listings
                    
                if isinstance(data, list):
                    logger.info(f"Retrieved {len(data)} total job items from Atlassian endpoint.")
                    for item in data:
                        job_id = str(item.get("id") or "")
                        title = (item.get("title") or "").strip()
                        dept = (item.get("department") or "").strip().lower()
                        locs = [str(l).lower() for l in item.get("locations", [])]
                        title_lower = title.lower()
                        
                        # Filter team=Engineering
                        is_eng = "engineering" in dept or any(k in title_lower for k in eng_keywords)
                        if not is_eng:
                            continue
                            
                        # Filter location=India
                        is_india = any("india" in l or "bengaluru" in l or "bangalore" in l for l in locs) or "india" in title_lower
                        if not is_india:
                            continue
                            
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            portal_url = item.get("portalJobPost", {}).get("portalUrl") or f"https://www.atlassian.com/company/careers/details/{job_id}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=portal_url
                                )
                            )
                            
            except Exception as e:
                logger.error(f"Failed to scrape Atlassian Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Atlassian Careers scrape. Found total {len(listings)} listings.")
        return listings
