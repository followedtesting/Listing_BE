import json
import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class LSEGPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "lseg_careers"

    @property
    def portal_name(self) -> str:
        return "LSEG Careers (Workday)"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://lseg.wd3.myworkdayjobs.com/en-US/Careers?CF_Lookup_Business_Unit_Level_02__Job_Posting_Anchor__Extended=9c1f71183c10016d116d72382401ff75&locationCountry=c4f78be1a8f14da0ab49ce1162348a5e"
        api_url = "https://lseg.wd3.myworkdayjobs.com/wday/cxs/lseg/Careers/jobs"
        logger.info(f"Navigating to LSEG Workday Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 20
        total_jobs = None
        
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
                    payload = {
                        "appliedFacets": {
                            "locationCountry": ["c4f78be1a8f14da0ab49ce1162348a5e"],
                            "CF_Lookup_Business_Unit_Level_02__Job_Posting_Anchor__Extended": ["9c1f71183c10016d116d72382401ff75"]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }
                    
                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    method: 'POST',
                                    headers: {{
                                        'Content-Type': 'application/json',
                                        'Accept': 'application/json'
                                    }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)
                    
                    if not isinstance(data, dict) or "jobPostings" not in data:
                        logger.error(f"Error or unexpected payload at offset {offset}: {data}")
                        break
                        
                    if total_jobs is None:
                        total_jobs = data.get("total", 0)
                        
                    postings = data.get("jobPostings", [])
                    logger.info(f"Retrieved {len(postings)} jobs from Workday API for LSEG (offset {offset}, total {total_jobs}).")
                    
                    if not postings:
                        break
                        
                    for job in postings:
                        title = (job.get("title") or "").strip()
                        external_path = (job.get("externalPath") or "").strip()
                        bullet_fields = job.get("bulletFields", [])
                        req_id = bullet_fields[0] if bullet_fields else ""
                        
                        job_id = external_path.split("/")[-1] if external_path else (req_id or title)
                        
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            full_link = f"https://lseg.wd3.myworkdayjobs.com/en-US/Careers{external_path}"
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
                logger.error(f"Failed to scrape LSEG Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished LSEG Careers scrape. Found total {len(listings)} listings.")
        return listings
