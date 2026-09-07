import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing
import urllib.parse

logger = logging.getLogger(__name__)

class AMDPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "amd_careers"

    @property
    def portal_name(self) -> str:
        return "AMD Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://careers.amd.com/careers-home/jobs?country=India&categories=Engineering"
        logger.info(f"Navigating to AMD Careers page to scrape listings.")
        
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
                    logger.info(f"Scraping AMD Careers page {page_num}: {url}")
                    
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as nav_err:
                        logger.warning(f"Non-fatal navigation warning/timeout: {nav_err}")
                        
                    await page.wait_for_timeout(5000)
                    
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and title and "/careers-home/jobs/" in href.lower():
                            href_clean = href.strip()
                            title_clean = title.strip().replace("\n", " ")
                            
                            # ignore "Apply Now" buttons
                            if "apply" in title_clean.lower() or "login" in title_clean.lower():
                                continue
                                
                            parts = href_clean.split("?")[0].split("/")
                            jobid = parts[-1]
                                
                            if jobid and title_clean:
                                if jobid in seen_ids:
                                    continue
                                    
                                seen_ids.add(jobid)
                                page_listings_count += 1
                                
                                if href_clean.startswith("http"):
                                    job_listing_link = href_clean
                                else:
                                    if not href_clean.startswith("/"):
                                        href_clean = "/" + href_clean
                                    job_listing_link = f"https://careers.amd.com{href_clean}"
                                    
                                listings.append(
                                    JobListing(
                                        jobid=jobid.strip(),
                                        role_name=title_clean,
                                        job_listing_link=job_listing_link
                                    )
                                )
                                
                    if page_listings_count == 0:
                        logger.info("Reached end of distinct listings.")
                        break
                        
                    logger.info(f"Found {page_listings_count} job postings on page {page_num}.")
                    
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape AMD Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished AMD Careers scrape. Found total {len(listings)} listings.")
        return listings
