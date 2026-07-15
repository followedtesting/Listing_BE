import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class StandardCharteredPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "standard_chartered_careers"

    @property
    def portal_name(self) -> str:
        return "Standard Chartered Careers Portal"

    async def scrape(self) -> List[JobListing]:
        facet_filters = "%7B%22cust_region%22%3A%5B%22Asia%22%5D%2C%22jobLocationCountry%22%3A%5B%22India%22%5D%2C%22mfield1%22%3A%5B%22Technology%22%5D%7D"
        logger.info("Starting Standard Chartered Careers scrape...")
        
        listings: List[JobListing] = []
        seen_ids = set()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                # Use standard Chrome User-Agent and desktop viewport to bypass bot protection
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                )
                page = await context.new_page()
                
                page_num = 0
                max_pages = 25  # Safeguard cap
                
                while page_num < max_pages:
                    url = (
                        f"https://jobs.standardchartered.com/go/Experienced-Professional-jobs/9783657/"
                        f"?markerViewed=&carouselIndex=&facetFilters={facet_filters}&pageNumber={page_num}&sortBy=date"
                    )
                    logger.info(f"Loading Standard Chartered pageNumber {page_num}: {url}")
                    
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as nav_err:
                        logger.warning(f"Non-fatal navigation warning/timeout on pageNumber {page_num}: {nav_err}")
                        
                    # Wait for SuccessFactors list to hydrate
                    await page.wait_for_timeout(4000)
                    
                    # Fetch links in the DOM
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and "/job/" in href.lower():
                            parts = href.strip().split("/")
                            # SuccessFactors pattern: /job/[SLUG]/[NUMBER]-[LOCALE]
                            # Example: /job/Assoc%2C-Full-Stack-Eng-MF%2C-WRB-Tech/57381-en_GB
                            last_seg = parts[-1]
                            jobid = ""
                            if "-" in last_seg:
                                jobid_part = last_seg.split("-")[0]
                                if jobid_part.isdigit():
                                    jobid = jobid_part
                                    
                            title_clean = title.strip()
                            
                            if jobid and title_clean:
                                if jobid in seen_ids:
                                    logger.info(f"Encountered duplicate jobid '{jobid}' on pageNumber {page_num}. Stopping pagination.")
                                    duplicate_found = True
                                    break
                                    
                                seen_ids.add(jobid)
                                page_listings_count += 1
                                
                                # Format absolute URL
                                if href.startswith("http"):
                                    job_listing_link = href.strip()
                                else:
                                    job_listing_link = f"https://jobs.standardchartered.com{href.strip()}"
                                    
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
                        logger.info(f"No job postings found on pageNumber {page_num}. Stopping pagination.")
                        break
                        
                    logger.info(f"Scraped {page_listings_count} job postings from pageNumber {page_num}.")
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape Standard Chartered Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Standard Chartered Careers scrape. Found total {len(listings)} listings.")
        return listings
