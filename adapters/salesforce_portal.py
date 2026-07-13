import logging
import json
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class SalesforcePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "salesforce_careers"

    @property
    def portal_name(self) -> str:
        return "Salesforce Careers Portal"

    async def scrape(self) -> List[JobListing]:
        # Base URL to establish cookies, CORS context and session parameters
        base_url = "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site"
        logger.info(f"Navigating to Salesforce Careers page to establish session context: {base_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                
                # Navigate to the search page to load session cookies
                await page.goto(base_url, wait_until="load")
                
                # Wait for page to initialize completely
                await page.wait_for_timeout(3000)
                
                offset = 0
                limit = 20
                max_safety_limit = 200  # Avoid runaway loop
                
                while offset < max_safety_limit:
                    logger.info(f"Fetching Salesforce careers listings starting at offset {offset}...")
                    
                    # Prepare POST request payload with exact filters for India and Software Engineering
                    payload = {
                        "appliedFacets": {
                            "CF_-_REC_-_LRV_-_Job_Posting_Anchor_-_Country_from_Job_Posting_Location_Extended": ["c4f78be1a8f14da0ab49ce1162348a5e"],
                            "jobFamilyGroup": ["14fa3452ec7c1011f90d0002a2100000"]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }
                    
                    # Execute fetch via page.evaluate
                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('/wday/cxs/salesforce/External_Career_Site/jobs', {{
                                    method: 'POST',
                                    headers: {{
                                        'Content-Type': 'application/json',
                                        'Accept': 'application/json'
                                    }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                if (!response.ok) {{
                                    return {{ error: `HTTP status ${{response.status}}` }};
                                }}
                                return await response.json();
                            }} catch (err) {{
                                return {{ error: err.message }};
                            }}
                        }}
                    """)
                    
                    if not result:
                        logger.warning(f"Salesforce Careers API call at offset {offset} returned empty result.")
                        break
                        
                    if "error" in result and result["error"]:
                        logger.error(f"Error fetching from Salesforce API at offset {offset}: {result['error']}")
                        break
                        
                    job_postings = result.get("jobPostings", [])
                    if not job_postings or len(job_postings) == 0:
                        logger.info(f"No more jobs found in Salesforce response at offset {offset}. Stopping pagination.")
                        break
                        
                    logger.info(f"Retrieved {len(job_postings)} job postings from Salesforce Careers at offset {offset}.")
                    
                    duplicate_found = False
                    for job in job_postings:
                        title = job.get("title", "")
                        ext_path = job.get("externalPath", "")
                        bullet_fields = job.get("bulletFields", [])
                        
                        # Get jobid from bulletFields list's first member if length > 0
                        jobid = ""
                        if bullet_fields and len(bullet_fields) > 0:
                            jobid = str(bullet_fields[0]).strip()
                            
                        # If jobid is not found, fallback to parsing/extracting from externalPath
                        if not jobid:
                            if "_" in ext_path:
                                jobid = ext_path.split("_")[-1]
                            else:
                                jobid = ext_path.split("/")[-1]
                        
                        if jobid in seen_ids:
                            logger.info(f"Encountered duplicate jobid '{jobid}' (reached end of distinct postings). Stopping pagination.")
                            duplicate_found = True
                            break
                            
                        seen_ids.add(jobid)
                        
                        # Build absolute URL from externalPath
                        if ext_path.startswith("http"):
                            job_listing_link = ext_path
                        else:
                            job_listing_link = f"https://salesforce.wd12.myworkdayjobs.com/External_Career_Site{ext_path}"
                            
                        if jobid and title and job_listing_link:
                            listings.append(
                                JobListing(
                                    jobid=jobid.strip(),
                                    role_name=title.strip(),
                                    job_listing_link=job_listing_link.strip()
                                )
                            )
                            
                    if duplicate_found:
                        break
                        
                    offset += limit
                    
            except Exception as e:
                logger.error(f"Failed to scrape Salesforce Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Salesforce Careers scrape. Found total {len(listings)} listings.")
        return listings
