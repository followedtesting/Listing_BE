import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NielsenIQPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "nielseniq_careers"

    @property
    def portal_name(self) -> str:
        return "NielsenIQ Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://nielseniq.com/?s=&market=global&language=en&orderby=date&order=DESC&post_type=career_job&job_locations=india&job_teams=technology%2Ctechnology-engineering&job_types="
        logger.info(f"Navigating to NielsenIQ Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        india_cities = ["pune", "vadodara", "chennai", "gurgaon", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "noida"]
        tech_keywords = ["software", "engineer", "developer", "architect", "data", "qa", "sre", "devops", "tech", "platform", "infrastructure", "backend", "frontend", "full stack"]
        
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
                
                offset = 0
                limit = 100
                
                while True:
                    api_url = f"https://api.smartrecruiters.com/v1/companies/NielsenIQ/postings?limit={limit}&offset={offset}"
                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}');
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)
                    
                    if not isinstance(data, dict) or "error" in data:
                        logger.error(f"Error fetching NielsenIQ postings at offset {offset}: {data.get('error') if isinstance(data, dict) else 'Invalid response'}")
                        break
                        
                    total = data.get("totalFound", 0)
                    items = data.get("content", [])
                    logger.info(f"Retrieved {len(items)} items from SmartRecruiters API for NielsenIQ (offset {offset}, total {total}).")
                    
                    if not items:
                        break
                        
                    for item in items:
                        loc = item.get("location", {})
                        country = (loc.get("country") or "").strip().lower()
                        city = (loc.get("city") or "").strip().lower()
                        full_loc = (loc.get("fullLocation") or "").strip().lower()
                        
                        is_india = country in ["in", "india"] or "india" in full_loc or any(c in city for c in india_cities)
                        if not is_india:
                            continue
                            
                        # Collect team / department labels
                        team_labels = set()
                        dept = item.get("department", {})
                        if dept.get("label"): team_labels.add(dept["label"].lower())
                        
                        fn = item.get("function", {})
                        if fn.get("label"): team_labels.add(fn["label"].lower())
                        
                        custom_fields = item.get("customField", [])
                        for cf in custom_fields:
                            v_label = cf.get("valueLabel")
                            if v_label:
                                team_labels.add(v_label.lower())
                                
                        title = (item.get("name") or "").strip()
                        title_lower = title.lower()
                        
                        # Match Technology or Technology Engineering or tech role title
                        is_tech = any("technology" in t or "engineering" in t or "tech" in t for t in team_labels)
                        if not is_tech:
                            is_tech = any(k in title_lower for k in tech_keywords)
                            
                        if is_tech:
                            job_id = str(item.get("id") or "").strip()
                            ref_num = str(item.get("refNumber") or "").strip()
                            ref_id = ref_num or job_id
                            
                            if ref_id and title and ref_id not in seen_ids:
                                seen_ids.add(ref_id)
                                full_link = f"https://jobs.smartrecruiters.com/NielsenIQ/{job_id}"
                                listings.append(
                                    JobListing(
                                        jobid=ref_id,
                                        role_name=title,
                                        job_listing_link=full_link
                                    )
                                )
                                
                    if len(items) < limit or offset + len(items) >= total:
                        break
                        
                    offset += limit
                    
            except Exception as e:
                logger.error(f"Failed to scrape NielsenIQ Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished NielsenIQ Careers scrape. Found total {len(listings)} listings.")
        return listings
