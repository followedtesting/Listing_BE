import logging
import json
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MaerskPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "maersk_careers"

    @property
    def portal_name(self) -> str:
        return "Maersk Careers Portal"

    async def scrape(self) -> List[JobListing]:
        # Base URL to establish cookies, CORS context and session parameters
        base_url = "https://maersk.wd3.myworkdayjobs.com/Maersk_Careers"
        logger.info(f"Navigating to Maersk Careers page to establish session context: {base_url}")
        
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
                    logger.info(f"Fetching Maersk careers listings starting at offset {offset}...")
                    
                    # Prepare POST request payload with exact filters
                    payload = {
                        "appliedFacets": {
                            "locations": [
                                '4140682c689310014db3b323f82e0000', 'b726e4845aaf1000ae23f229f2170000',
                                'ac1e3f63dcb61001484cca8da0ee0000', '7b99c86bc5751001ee77c1dad0500000',
                                '7b88c76f001e10009e153d90f32d0000', '26c4d72049dc10009e1694dea72b0000',
                                'd8801e5af43d10009e1bfb079d6e0000', 'e78dddcb583810009e1b32f6dc380000',
                                'd8801e5af43d10009e1c6f60d76f0000', 'e78dddcb583810009e1299afb33f0000',
                                '7b88c76f001e10009e104f5ac5710000', '5fb6db3471ab10009e00c2b0912f0000',
                                'e78dddcb583810009dfef15511dd0000', '7b88c76f001e10009e1081ca16fc0000',
                                'd8801e5af43d10009e04f442bf430000', '9de49f588a0f10009e1c35c6900a0000',
                                'd8801e5af43d10009df3a49ebd480000', 'e27b2cd8aca310009e0d527ac7650000',
                                '7a38998ecd771001354b00da72100000', 'e78dddcb583810009e08889eadfe0000',
                                'ddba4775944910009e424afe3f850000', 'd8801e5af43d10009e0f6cca3a670000',
                                '5fb6db3471ab10009df11e5466840000', '26c4d72049dc10009e1c3d2fa2b50000',
                                'e27b2cd8aca310009e1a44220f6c0000', '5fb6db3471ab10009e0918d15dce0000',
                                'd8801e5af43d10009dfa3a8079340000', 'ddba4775944910009e1b192970560000',
                                '15350d48499210009e07c02b134d0000', '15350d48499210009e017164bb040000',
                                '853120f5cc8a10009e388f5d2aec0000', '15350d48499210009e1dac6cee0f0000',
                                '36d739e3210410014d09a17767590000', '260b68637fef1001e2bd40927d560000',
                                '9cbc082ae7f910013707c12d02c50000', '4e4d26638c45010787a37d5e5ad00000',
                                'c64e2feaec101001518738d6a9190000', '72baf0a31a0610014d090d9200e60000',
                                'f65203ee21d11001dc15d8486e340000', '4e4d26638c450107879f5562654c0000',
                                'fea35a9107ff10014ce73a337d340000', '4e4d26638c450107879f40e6fff00000',
                                '8df45049b43810013bfc511ded230000', '6fbaf2e5eafd1001035bccb694910000',
                                '4e4d26638c45010787a265e08d260000', '4e4d26638c45010787a25f43fa5f0000',
                                '4e4d26638c45010787a25b0edea60000', '0829310dd78f100197add0dc5cc90000',
                                '4e4d26638c45010787a4082f00a70000', '4e4d26638c45010787a25209b00e0000',
                                '4e4d26638c450107879f19c9b39b0000'
                            ],
                            "jobFamilyGroup": ["0d1a9a0723441001ef28e3fa8deb0000"]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }
                    
                    # Execute fetch via page.evaluate
                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('/wday/cxs/maersk/Maersk_Careers/jobs', {{
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
                        logger.warning(f"Maersk Careers API call at offset {offset} returned empty result.")
                        break
                        
                    if "error" in result and result["error"]:
                        logger.error(f"Error fetching from Maersk API at offset {offset}: {result['error']}")
                        break
                        
                    job_postings = result.get("jobPostings", [])
                    if not job_postings or len(job_postings) == 0:
                        logger.info(f"No more jobs found in Maersk response at offset {offset}. Stopping pagination.")
                        break
                        
                    logger.info(f"Retrieved {len(job_postings)} job postings from Maersk Careers at offset {offset}.")
                    
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
                            job_listing_link = f"https://maersk.wd3.myworkdayjobs.com/Maersk_Careers{ext_path}"
                            
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
                logger.error(f"Failed to scrape Maersk Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Maersk Careers scrape. Found total {len(listings)} listings.")
        return listings
