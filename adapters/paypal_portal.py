import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PaypalPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "paypal_careers"

    @property
    def portal_name(self) -> str:
        return "PayPal Careers Portal"

    async def scrape(self) -> List[JobListing]:
        # Removed the 'pid' parameter from the user's URL so we get the main search view without a selected job
        base_url = "https://paypal.eightfold.ai/careers?domain=paypal.com&location=india&sort_by=distance&filter_include_remote=1&filter_include_relocation=0&filter_job_category=Software+Engineering"
        logger.info(f"Navigating to PayPal Eightfold page to scrape listings.")
        
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
                
                start_index = 0
                max_pages = 20
                limit = 10
                
                while start_index < (max_pages * limit):
                    url = f"{base_url}&start={start_index}"
                    logger.info(f"Scraping PayPal Careers page at start={start_index}: {url}")
                    
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as nav_err:
                        logger.warning(f"Non-fatal navigation warning/timeout: {nav_err}")
                        
                    await page.wait_for_timeout(5000)
                    
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and title and "/careers/job/" in href.lower():
                            href_clean = href.strip()
                            title_clean = title.strip().replace("\n", " | ")
                            
                            parts = href_clean.split("?")[0].split("/")
                            jobid = parts[-1]
                            
                            if jobid and title_clean:
                                # Eightfold sometimes returns jobs from other countries when it exhausts local ones
                                if "india" not in title_clean.lower():
                                    continue
                                    
                                if jobid in seen_ids:
                                    continue
                                    
                                seen_ids.add(jobid)
                                page_listings_count += 1
                                
                                if href_clean.startswith("http"):
                                    job_listing_link = href_clean
                                else:
                                    if not href_clean.startswith("/"):
                                        href_clean = "/" + href_clean
                                    job_listing_link = f"https://paypal.eightfold.ai{href_clean}"
                                    
                                listings.append(
                                    JobListing(
                                        jobid=jobid.strip(),
                                        role_name=title_clean,
                                        job_listing_link=job_listing_link
                                    )
                                )
                                
                    if page_listings_count == 0:
                        logger.info("Reached end of distinct listings or no jobs found.")
                        break
                        
                    logger.info(f"Found {page_listings_count} job postings at start={start_index}.")
                    start_index += limit
                    
            except Exception as e:
                logger.error(f"Failed to scrape PayPal Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished PayPal Careers scrape. Found total {len(listings)} listings.")
        return listings
