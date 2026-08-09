import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MeeshoPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "meesho_careers"

    @property
    def portal_name(self) -> str:
        return "Meesho Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://www.meesho.io/jobs?d=engineering"
        logger.info(f"Navigating to Meesho Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        
        eng_teams = {
            "demand", "supply & fulfilment", "qa", "infrastructure",
            "cto office", "data engineering", "frontend", "backend",
            "security", "ai services", "data science", "engineering", "tech", "technology"
        }
        
        tech_keywords = [
            "software", "engineer", "developer", "architect", "data", "qa",
            "sre", "devops", "tech", "platform", "backend", "frontend", "sdm", "em", "tech lead"
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
                
                lever_url = "https://api.lever.co/v0/postings/meesho?mode=json"
                items = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const response = await fetch('{lever_url}');
                            return await response.json();
                        }} catch (err) {{
                            return [{{ "error": err.message }}];
                        }}
                    }}
                """)
                
                if not isinstance(items, list):
                    logger.error(f"Invalid response from Lever API for Meesho: {items}")
                    return []
                    
                logger.info(f"Retrieved {len(items)} total job postings from Lever API for Meesho.")
                
                for item in items:
                    if not isinstance(item, dict) or "error" in item:
                        continue
                        
                    team = (item.get("categories", {}).get("team") or "").strip().lower()
                    dept = (item.get("categories", {}).get("department") or "").strip().lower()
                    title = (item.get("text") or "").strip()
                    title_lower = title.lower()
                    
                    is_eng = team in eng_teams or dept in eng_teams or any(k in title_lower for k in tech_keywords)
                    
                    # Filter out non-engineering compliance / hardware / non-tech roles
                    if "compliance" in title_lower or "hardware" in team:
                        is_eng = False
                        
                    if is_eng:
                        job_id = str(item.get("id") or "").strip()
                        link = str(item.get("hostedUrl") or "").strip()
                        
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=link or f"https://jobs.lever.co/meesho/{job_id}"
                                )
                            )
                            
            except Exception as e:
                logger.error(f"Failed to scrape Meesho Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Meesho Careers scrape. Found total {len(listings)} listings.")
        return listings
