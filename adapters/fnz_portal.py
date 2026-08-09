import json
import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class FNZPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "fnz_careers"

    @property
    def portal_name(self) -> str:
        return "FNZ Careers (Workday)"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://fnz.wd3.myworkdayjobs.com/fnz_careers?locations=31271d7456e91000a36e20ee17880000&locations=26b4b1c50b071000a34557ea0fc30000&locations=5de2101ab31410014829e9e398f70000&jobFamilyGroup=499f8fb040731000f2de59223f570000"
        wday_endpoint = "https://fnz.wd3.myworkdayjobs.com/wday/cxs/fnz/fnz_careers/jobs"
        logger.info(f"Navigating to FNZ Workday Careers: {target_url}")
        
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
                            "locations": [
                                "31271d7456e91000a36e20ee17880000",
                                "26b4b1c50b071000a34557ea0fc30000",
                                "5de2101ab31410014829e9e398f70000"
                            ],
                            "jobFamilyGroup": [
                                "499f8fb040731000f2de59223f570000"
                            ]
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
                        logger.error(f"Error fetching FNZ Workday jobs at offset {offset}: {data}")
                        break
                        
                    total = data.get("total", 0)
                    postings = data.get("jobPostings", [])
                    logger.info(f"Retrieved {len(postings)} jobs from Workday API for FNZ (offset {offset}, total {total}).")
                    
                    if not postings:
                        break
                        
                    for job in postings:
                        title = (job.get("title") or "").strip()
                        ext_path = (job.get("externalPath") or "").strip()
                        bullets = job.get("bulletFields", [])
                        
                        job_id = None
                        for b in bullets:
                            if b.startswith("REQ") or b.startswith("R") or b.isdigit():
                                job_id = b
                                break
                        if not job_id and ext_path:
                            job_id = ext_path.rstrip("/").split("/")[-1]
                            
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            full_link = f"https://fnz.wd3.myworkdayjobs.com/en-US/fnz_careers{ext_path}"
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
                logger.error(f"Failed to scrape FNZ Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished FNZ Careers scrape. Found total {len(listings)} listings.")
        return listings
