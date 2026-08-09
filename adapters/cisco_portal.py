import logging
import json
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class CiscoPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "cisco_careers"

    @property
    def portal_name(self) -> str:
        return "Cisco Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://careers.cisco.com/global/en/c/product-and-engineering-jobs"
        logger.info(f"Navigating to Cisco Careers page to establish session context: {base_url}")
        
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
                await page.wait_for_timeout(3000)
                
                from_offset = 0
                page_size = 100
                max_offset = 2000
                api_url = "https://careers.cisco.com/widgets"
                
                while from_offset < max_offset:
                    logger.info(f"Fetching Cisco careers Product & Engineering (India) offset {from_offset}...")
                    
                    payload = {
                        "sortBy": "",
                        "subsearch": "",
                        "from": from_offset,
                        "jobs": True,
                        "counts": True,
                        "all_fields": ["category", "country", "state", "city"],
                        "pageName": "search-results",
                        "size": page_size,
                        "clearAll": False,
                        "jdsource": "facets",
                        "isSliderEnable": False,
                        "pageId": "page4",
                        "siteType": "external",
                        "keywords": "",
                        "global": True,
                        "selected_fields": {
                            "category": ["Product and Engineering"],
                            "country": ["India"]
                        },
                        "lang": "en_global",
                        "deviceType": "desktop",
                        "country": "global",
                        "refNum": "CISCISGLOBAL",
                        "ddoKey": "refineSearch"
                    }
                    
                    payload_str = json.dumps(payload)
                    
                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    method: 'POST',
                                    headers: {{ 'Content-Type': 'application/json' }},
                                    body: JSON.stringify({payload_str})
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)
                    
                    if "error" in result:
                        logger.error(f"Error fetching Cisco listings at offset {from_offset}: {result['error']}")
                        break
                        
                    refine = result.get("refineSearch", {})
                    total_hits = refine.get("totalHits", 0)
                    jobs = refine.get("data", {}).get("jobs", [])
                    
                    if not jobs:
                        logger.info(f"No jobs returned from Cisco API at offset {from_offset}. Stopping pagination.")
                        break
                        
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for job in jobs:
                        job_id = str(job.get("jobId") or job.get("jobSeqNo") or "").strip()
                        title = str(job.get("title") or "").strip()
                        
                        if job_id and title:
                            if job_id in seen_ids:
                                logger.info(f"Encountered duplicate job_id '{job_id}' at offset {from_offset}. Stopping pagination.")
                                duplicate_found = True
                                break
                                
                            seen_ids.add(job_id)
                            page_listings_count += 1
                            job_link = f"https://careers.cisco.com/global/en/job/{job_id}/"
                            
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=job_link
                                )
                            )
                            
                    logger.info(f"Scraped {page_listings_count} jobs from Cisco offset {from_offset}.")
                    
                    if duplicate_found or len(jobs) < page_size or (total_hits and len(seen_ids) >= total_hits):
                        logger.info(f"Reached end of listings for Cisco (total scraped: {len(seen_ids)}, total available: {total_hits}). Stopping pagination.")
                        break
                        
                    from_offset += page_size
                    
            except Exception as e:
                logger.error(f"Failed to scrape Cisco Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Cisco Careers scrape. Found total {len(listings)} listings.")
        return listings
