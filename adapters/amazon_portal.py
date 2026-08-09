import logging
import json
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AmazonPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "amazon_careers"

    @property
    def portal_name(self) -> str:
        return "Amazon Jobs Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://www.amazon.jobs/en-gb/search?offset=0&result_limit=10&sort=recent&category%5B%5D=software-development&country%5B%5D=IND"
        logger.info(f"Navigating to Amazon Jobs page to establish session context: {base_url}")
        
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
                
                await page.goto(base_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                
                offset = 0
                page_size = 100
                max_offset = 3000
                
                while offset < max_offset:
                    logger.info(f"Fetching Amazon Software Development (India) jobs offset {offset}...")
                    api_url = f"https://www.amazon.jobs/en-gb/search.json?category%5B%5D=software-development&normalized_country_code%5B%5D=IND&offset={offset}&result_limit={page_size}&sort=recent"
                    
                    res_data = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    headers: {{
                                        'Accept': 'application/json',
                                        'X-Requested-With': 'XMLHttpRequest'
                                    }}
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)
                    
                    if res_data.get("error") is not None:
                        logger.error(f"Error fetching Amazon listings at offset {offset}: {res_data['error']}")
                        break
                        
                    hits = res_data.get("hits", 0)
                    jobs = res_data.get("jobs", [])
                    
                    if not jobs:
                        logger.info(f"No jobs returned from Amazon API at offset {offset}. Stopping pagination.")
                        break
                        
                    page_added = 0
                    duplicate_found = False
                    
                    for job in jobs:
                        job_id = str(job.get("id_icims") or "").strip()
                        title = str(job.get("title") or "").strip()
                        job_path = str(job.get("job_path") or "").strip()
                        
                        if job_id and title:
                            if job_id in seen_ids:
                                logger.info(f"Encountered duplicate job_id '{job_id}' at offset {offset}. Stopping pagination.")
                                duplicate_found = True
                                break
                                
                            seen_ids.add(job_id)
                            full_link = f"https://www.amazon.jobs{job_path}" if job_path.startswith("/") else f"https://www.amazon.jobs/en-gb/jobs/{job_id}"
                            
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )
                            page_added += 1
                            
                    logger.info(f"Scraped {page_added} jobs from Amazon offset {offset}.")
                    
                    if duplicate_found or len(jobs) < page_size or (hits and len(seen_ids) >= hits):
                        logger.info(f"Reached end of listings for Amazon (total scraped: {len(seen_ids)}, total available: {hits}). Stopping pagination.")
                        break
                        
                    offset += page_size
                    
            except Exception as e:
                logger.error(f"Failed to scrape Amazon Jobs Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Amazon Jobs scrape. Found total {len(listings)} listings.")
        return listings
