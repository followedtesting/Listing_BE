import logging
import json
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AkamaiPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "akamai_careers"

    @property
    def portal_name(self) -> str:
        return "Akamai Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://jobs.akamai.com/en/sites/CX_1/jobs?lastSelectedFacet=TITLES&location=India&locationId=300000000469285&locationLevel=country&mode=location&selectedTitlesFacet=ENG"
        logger.info(f"Navigating to Akamai Careers page to set session context: {base_url}")
        
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
                
                # Load context
                await page.goto(base_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(5000)
                
                offset = 0
                limit = 25
                max_safety_limit = 200  # Avoid runaway loop
                
                while offset < max_safety_limit:
                    logger.info(f"Fetching Akamai careers listings starting at offset {offset}...")
                    
                    # Prepare API URL
                    rest_api_url = "https://fa-extu-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                    finder = f"findReqs;siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit={limit},offset={offset},lastSelectedFacet=TITLES,locationId=300000000469285,selectedTitlesFacet=ENG,sortBy=POSTING_DATES_DESC"
                    api_url = f"{rest_api_url}?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder={finder}"
                    
                    # Fetch JSON inside browser page context to pass CORS/WAF cleanly
                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}');
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)
                    
                    if "error" in result:
                        logger.error(f"Error fetching Akamai listings at offset {offset} inside browser: {result['error']}")
                        break
                        
                    items = result.get("items", [])
                    if not items:
                        logger.info(f"No items returned from Akamai search API at offset {offset}. Stopping pagination.")
                        break
                        
                    req_list = items[0].get("requisitionList", [])
                    if not req_list:
                        logger.info(f"No requisitions returned in list at offset {offset}. Stopping pagination.")
                        break
                        
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for req in req_list:
                        jobid = req.get("Id")
                        title = req.get("Title")
                        
                        if jobid and title:
                            jobid_str = str(jobid).strip()
                            if jobid_str in seen_ids:
                                logger.info(f"Encountered duplicate jobid '{jobid_str}' at offset {offset}. Stopping pagination.")
                                duplicate_found = True
                                break
                                
                            seen_ids.add(jobid_str)
                            page_listings_count += 1
                            
                            job_listing_link = f"https://jobs.akamai.com/en/sites/CX_1/job/{jobid_str}"
                            listings.append(
                                JobListing(
                                    jobid=jobid_str,
                                    role_name=title.strip(),
                                    job_listing_link=job_listing_link
                                )
                            )
                            
                    if duplicate_found:
                        break
                        
                    logger.info(f"Scraped {page_listings_count} jobs from offset {offset}.")
                    offset += limit
                    
            except Exception as e:
                logger.error(f"Failed to scrape Akamai Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Akamai Careers scrape. Found total {len(listings)} listings.")
        return listings
