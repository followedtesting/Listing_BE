import logging
import urllib.parse
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MicrosoftPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "microsoft_careers"

    @property
    def portal_name(self) -> str:
        return "Microsoft Careers Portal"

    async def scrape(self) -> List[JobListing]:
        query_params = {
            "hl": "en",
            "query": "Software Engineer",
            "start": "0",
            "location": "India",
            "sort_by": "timestamp",
            "filter_include_remote": "1"
        }
        # Construct the initial navigation URL to set cookies and context
        nav_query = urllib.parse.urlencode(query_params)
        base_url = f"https://apply.careers.microsoft.com/careers?{nav_query}"
        
        logger.info(f"Navigating to Microsoft Careers page to set session cookies: {base_url}")
        
        listings: List[JobListing] = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                
                # Navigate to the base careers page
                await page.goto(base_url, wait_until="load")
                
                # Allow a short delay for dynamic cookies/sessions to load
                await page.wait_for_timeout(3000)
                
                start = 0
                page_size = 10
                max_safety_limit = 200  # Prevent infinite loops in case API format breaks
                
                while start < max_safety_limit:
                    logger.info(f"Fetching Microsoft careers listings starting at offset {start}...")
                    
                    # Construct search API query parameters
                    search_params = {
                        "domain": "microsoft.com",
                        "query": "Software Engineer",
                        "location": "India",
                        "start": str(start),
                        "sort_by": "timestamp",
                        "filter_include_remote": "1",
                        "hl": "en"
                    }
                    api_query = urllib.parse.urlencode(search_params)
                    api_url = f"/api/pcsx/search?{api_query}"
                    
                    # Fetch inside page context to inherit active browser headers, cookies, and CORS context
                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch({repr(api_url)});
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
                        logger.warning(f"Microsoft Careers API call at start={start} returned empty result.")
                        break
                        
                    # Check status and error message
                    api_status = result.get("status", 200)
                    api_error = result.get("error") or {}
                    error_msg = api_error.get("message") if isinstance(api_error, dict) else str(api_error)
                    
                    if api_status != 200 or error_msg:
                        logger.error(f"Error fetching from Microsoft API at start={start}: Status {api_status}, Msg: {error_msg}")
                        break
                        
                    data = result.get("data", {})
                    positions = data.get("positions", [])
                    
                    if not positions or len(positions) == 0:
                        logger.info(f"No positions found in Microsoft response data at offset {start}. Stopping pagination.")
                        break
                        
                    logger.info(f"Retrieved {len(positions)} job positions from Microsoft Careers at offset {start}.")
                    
                    for pos in positions:
                        # Fetch DisplayJobId (user specified) or fallback to ID
                        jobid = str(pos.get("displayJobId") or pos.get("id"))
                        role_name = pos.get("name")
                        pos_url = pos.get("positionUrl", "")
                        
                        # Build absolute URL if relative
                        if pos_url.startswith("http"):
                            job_listing_link = pos_url
                        else:
                            job_listing_link = f"https://apply.careers.microsoft.com{pos_url}"
                            
                        if jobid and role_name and job_listing_link:
                            listings.append(
                                JobListing(
                                    jobid=jobid.strip(),
                                    role_name=role_name.strip(),
                                    job_listing_link=job_listing_link.strip()
                                )
                            )
                    
                    # Increment start offset by page size
                    start += page_size
                    
            except Exception as e:
                logger.error(f"Failed to scrape Microsoft Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Microsoft Careers scrape. Found total {len(listings)} listings.")
        return listings
