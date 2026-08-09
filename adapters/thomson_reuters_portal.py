import json
import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ThomsonReutersPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "thomson_reuters_careers"

    @property
    def portal_name(self) -> str:
        return "Thomson Reuters Careers (Workday)"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://thomsonreuters.wd5.myworkdayjobs.com/en-US/External_Career_Site?CF_Job_Posting_Anchor_Job_Category_EEB_Extended=9276a62d4e68100204e60c54e1cc0001&Location_Country=c4f78be1a8f14da0ab49ce1162348a5e"
        wday_endpoint = "https://thomsonreuters.wd5.myworkdayjobs.com/wday/cxs/thomsonreuters/External_Career_Site/jobs"
        logger.info(f"Navigating to Thomson Reuters Workday Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 20
        
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
                            "CF_Job_Posting_Anchor_Job_Category_EEB_Extended": ["9276a62d4e68100204e60c54e1cc0001"],
                            "Location_Country": ["c4f78be1a8f14da0ab49ce1162348a5e"]
                        },
                        "limit": limit,
                        "offset": offset,
                        "searchText": ""
                    }
                    
                    data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{wday_endpoint}', {{
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
                    
                    if not isinstance(data, dict) or "error" in data:
                        logger.error(f"Error fetching Thomson Reuters Workday jobs at offset {offset}: {data}")
                        break
                        
                    total = data.get("total", 0)
                    postings = data.get("jobPostings", [])
                    logger.info(f"Retrieved {len(postings)} jobs from Workday API for Thomson Reuters (offset {offset}, total {total}).")
                    
                    if not postings:
                        break
                        
                    for job in postings:
                        title = (job.get("title") or "").strip()
                        ext_path = (job.get("externalPath") or "").strip()
                        bullets = job.get("bulletFields", [])
                        
                        job_id = None
                        for b in bullets:
                            if b.startswith("JREQ") or b.startswith("R") or b.isdigit():
                                job_id = b
                                break
                        if not job_id and ext_path:
                            job_id = ext_path.rstrip("/").split("/")[-1]
                            
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            full_link = f"https://thomsonreuters.wd5.myworkdayjobs.com/en-US/External_Career_Site{ext_path}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )
                            
                    if len(postings) < limit or offset + len(postings) >= total:
                        break
                        
                    offset += limit
                    
            except Exception as e:
                logger.error(f"Failed to scrape Thomson Reuters Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Thomson Reuters Careers scrape. Found total {len(listings)} listings.")
        return listings
