import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing
import urllib.parse

logger = logging.getLogger(__name__)

class CventPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "cvent_careers"

    @property
    def portal_name(self) -> str:
        return "Cvent Careers Portal"

    async def scrape(self) -> List[JobListing]:
        # Using URL provided without hardcoded page=1 so we can iterate it
        base_url = "https://careers.cvent.com/jobs?tags2=Technology&locations=Gurugram,,India&categories=Site%20Reliability%20Engineering|Software%20Development|Technology"
        logger.info(f"Navigating to Cvent Careers page to scrape listings.")
        
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
                
                page_num = 1
                max_pages = 20
                
                while page_num <= max_pages:
                    url = f"{base_url}&page={page_num}"
                    logger.info(f"Scraping Cvent Careers page {page_num}: {url}")
                    
                    await page.goto(url, wait_until="networkidle", timeout=45000)
                    await page.wait_for_timeout(3000)
                    
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and "/jobs/" in href and title:
                            href_clean = href.strip()
                            title_clean = title.strip().replace("\n", " ")
                            
                            # Skip "Apply Now" links, which point to icims
                            if title_clean.lower() == "apply now":
                                continue
                                
                            # Extract jobid from "/jobs/10677?lang=en-us"
                            parts = href_clean.split("/")
                            jobid = ""
                            for p_item in parts:
                                if "?" in p_item:
                                    p_item = p_item.split("?")[0]
                                if p_item.isdigit():
                                    jobid = p_item
                                    break
                                    
                            if not jobid:
                                try:
                                    job_idx = parts.index("jobs")
                                    if job_idx + 1 < len(parts):
                                        possible_id = parts[job_idx + 1]
                                        if "?" in possible_id:
                                            possible_id = possible_id.split("?")[0]
                                        jobid = possible_id
                                except ValueError:
                                    pass
                                    
                            if jobid and title_clean:
                                if jobid in seen_ids:
                                    logger.info(f"Encountered duplicate jobid '{jobid}' on page {page_num}. Stopping pagination.")
                                    duplicate_found = True
                                    break
                                    
                                seen_ids.add(jobid)
                                page_listings_count += 1
                                
                                if href_clean.startswith("http"):
                                    job_listing_link = href_clean
                                else:
                                    job_listing_link = f"https://careers.cvent.com{href_clean}"
                                    
                                listings.append(
                                    JobListing(
                                        jobid=jobid.strip(),
                                        role_name=title_clean,
                                        job_listing_link=job_listing_link
                                    )
                                )
                                
                    if duplicate_found or page_listings_count == 0:
                        logger.info("Reached end of distinct listings.")
                        break
                        
                    logger.info(f"Found {page_listings_count} job postings on page {page_num}.")
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape Cvent Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Cvent Careers scrape. Found total {len(listings)} listings.")
        return listings
