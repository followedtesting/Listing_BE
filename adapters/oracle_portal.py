import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class OraclePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "oracle_careers"

    @property
    def portal_name(self) -> str:
        return "Oracle Careers (HCM Cloud)"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://careers.oracle.com/en/sites/jobsearch/jobs?lastSelectedFacet=CATEGORIES&location=India&locationId=300000000106947&selectedCategoriesFacet=300000001917356&selectedLocationsFacet=300000000106947"
        logger.info(f"Navigating to Oracle Cloud Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 25
        
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
                
                while True:
                    api_url = f"https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder=findReqs;siteNumber=CX_45001,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit={limit},offset={offset},lastSelectedFacet=CATEGORIES,locationId=300000000106947,selectedCategoriesFacet=300000001917356,selectedLocationsFacet=300000000106947,sortBy=POSTING_DATES_DESC"
                    
                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    headers: {{
                                        'Accept': 'application/json, text/plain, */*'
                                    }}
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)
                    
                    if not isinstance(data, dict) or "items" not in data or not data["items"]:
                        logger.error(f"Error or unexpected payload at offset {offset}: {data}")
                        break
                        
                    req_container = data["items"][0]
                    total_jobs = req_container.get("TotalJobsCount", 0)
                    postings = req_container.get("requisitionList", [])
                    logger.info(f"Retrieved {len(postings)} jobs from Oracle HCM API for Oracle Careers (offset {offset}, TotalJobsCount {total_jobs}).")
                    
                    if not postings:
                        break
                        
                    for job in postings:
                        job_id = str(job.get("Id") or job.get("RequisitionId") or "")
                        title = (job.get("Title") or "").strip()
                        
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            full_link = f"https://careers.oracle.com/en/sites/jobsearch/job/{job_id}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )
                            
                    if len(postings) < limit or offset + len(postings) >= total_jobs:
                        break
                        
                    offset += limit
                    
            except Exception as e:
                logger.error(f"Failed to scrape Oracle Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Oracle Careers scrape. Found total {len(listings)} listings.")
        return listings
