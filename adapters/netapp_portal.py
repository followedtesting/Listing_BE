import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NetAppPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "netapp_careers"

    @property
    def portal_name(self) -> str:
        return "NetApp Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://careers.netapp.com/search-jobs?k=&Country=1269750&State=&orgIds=27600"
        logger.info(f"Navigating to NetApp Careers: {target_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        india_cities = ["bengaluru", "bangalore", "mumbai", "chennai", "delhi", "hyderabad", "noida", "pune", "india"]
        page_num = 1
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                
                while True:
                    seo_url = f"https://careers.netapp.com/search-jobs/India/27600/{page_num}"
                    logger.info(f"Fetching NetApp India jobs page {page_num}: {seo_url}")
                    
                    await page.goto(seo_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)
                    
                    anchors = await page.query_selector_all("section#search-results a[href*='/job/'], ul a[href*='/job/'], a[href*='/job/']")
                    page_added = 0
                    
                    for a in anchors:
                        href = await a.get_attribute("href") or ""
                        text = await a.inner_text() or ""
                        title = text.strip().replace("\n", " ")
                        title_lower = title.lower()
                        href_lower = href.lower()
                        
                        is_india = "india" in title_lower or any(c in title_lower or f"/job/{c}/" in href_lower for c in india_cities)
                        if not is_india:
                            continue
                            
                        parts = [p for p in href.rstrip("/").split("/") if p]
                        job_id = None
                        if len(parts) >= 2 and parts[-1].isdigit():
                            job_id = parts[-1]
                        elif len(parts) >= 3 and parts[-2].isdigit():
                            job_id = parts[-2]
                        else:
                            job_id = href
                            
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            full_link = href if href.startswith("http") else f"https://careers.netapp.com{href}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )
                            page_added += 1
                            
                    logger.info(f"NetApp page {page_num}: Added {page_added} India listings (total so far: {len(listings)}).")
                    
                    if page_added == 0 or page_num >= 15:
                        break
                        
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape NetApp Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished NetApp Careers scrape. Found total {len(listings)} listings.")
        return listings
