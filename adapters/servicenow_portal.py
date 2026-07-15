import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ServiceNowPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "servicenow_careers"

    @property
    def portal_name(self) -> str:
        return "ServiceNow Careers Portal"

    async def scrape(self) -> List[JobListing]:
        query_str = "search=Software+Engineer&team=Early+In+Career&team=Engineering%2C+Infrastructure+and+Operations&country=India&pagesize=20"
        logger.info("Starting ServiceNow Careers scrape...")
        
        listings: List[JobListing] = []
        seen_ids = set()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                # Use standard Chrome User-Agent and desktop viewport to bypass any potential bot blocks
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                )
                page = await context.new_page()
                
                page_num = 1
                max_pages = 10  # Safeguard cap
                
                while page_num <= max_pages:
                    url = f"https://careers.servicenow.com/jobs/?page={page_num}&{query_str}#results"
                    logger.info(f"Loading ServiceNow page {page_num}: {url}")
                    
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as nav_err:
                        logger.warning(f"Non-fatal navigation warning/timeout on page {page_num}: {nav_err}")
                        
                    # Wait for page elements to settle
                    await page.wait_for_timeout(3000)
                    
                    # Fetch links in the DOM
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href:
                            parts = href.strip().split("/")
                            # Pattern matches: /jobs/[NUMBER]/[SLUG]/
                            if len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit():
                                jobid = parts[2]
                                title_clean = title.strip()
                                
                                if jobid in seen_ids:
                                    logger.info(f"Encountered duplicate jobid '{jobid}' on page {page_num}. Stopping pagination.")
                                    duplicate_found = True
                                    break
                                    
                                seen_ids.add(jobid)
                                page_listings_count += 1
                                
                                # Format absolute URL
                                if href.startswith("http"):
                                    job_listing_link = href.strip()
                                else:
                                    job_listing_link = f"https://careers.servicenow.com{href.strip()}"
                                    
                                if jobid and title_clean:
                                    listings.append(
                                        JobListing(
                                            jobid=jobid.strip(),
                                            role_name=title_clean,
                                            job_listing_link=job_listing_link
                                        )
                                    )
                                    
                    if duplicate_found:
                        break
                        
                    if page_listings_count == 0:
                        logger.info(f"No job postings found on page {page_num}. Stopping pagination.")
                        break
                        
                    logger.info(f"Scraped {page_listings_count} job postings from page {page_num}.")
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape ServiceNow Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished ServiceNow Careers scrape. Found total {len(listings)} listings.")
        return listings
