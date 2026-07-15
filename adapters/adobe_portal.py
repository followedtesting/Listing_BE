import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class AdobePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "adobe_careers"

    @property
    def portal_name(self) -> str:
        return "Adobe Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://careers.adobe.com/us/en/c/engineering-and-product-jobs"
        logger.info(f"Navigating to Adobe Careers page to set session context: {url}")
        
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
                
                # Navigate to the page
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as nav_err:
                    logger.warning(f"Non-fatal navigation warning/timeout (attempting to continue scrape): {nav_err}")
                
                # Allow a short delay for dynamic content to settle
                await page.wait_for_timeout(4000)
                
                # Click the "India" location filter checkbox/label directly (accordion is open by default)
                logger.info("Selecting India Country filter facet...")
                await page.click('label:has-text("India")')
                await page.wait_for_timeout(5000)
                
                page_num = 1
                max_pages = 20  # Safeguard cap
                
                while page_num <= max_pages:
                    logger.info(f"Scraping Adobe Careers page {page_num}...")
                    
                    # Fetch all visible links in the DOM
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        if href and "/job/" in href:
                            href_clean = href.strip()
                            title_clean = title.strip()
                            
                            # Parse job ID from url path (e.g. .../job/R167430/Senior-...)
                            parts = href_clean.split("/")
                            jobid = ""
                            try:
                                job_idx = parts.index("job")
                                if job_idx + 1 < len(parts):
                                    jobid = parts[job_idx + 1]
                            except ValueError:
                                pass
                                
                            if jobid and title_clean:
                                if jobid in seen_ids:
                                    logger.info(f"Encountered duplicate jobid '{jobid}' on page {page_num}. Stopping pagination.")
                                    duplicate_found = True
                                    break
                                    
                                seen_ids.add(jobid)
                                page_listings_count += 1
                                
                                # Format absolute URL
                                if href_clean.startswith("http"):
                                    job_listing_link = href_clean
                                else:
                                    job_listing_link = f"https://careers.adobe.com{href_clean}"
                                    
                                listings.append(
                                    JobListing(
                                        jobid=jobid.strip(),
                                        role_name=title_clean,
                                        job_listing_link=job_listing_link
                                    )
                                )
                                
                    if duplicate_found:
                        break
                        
                    logger.info(f"Found {page_listings_count} job postings on page {page_num}.")
                    
                    # Locate the "Next" button/link
                    next_button = await page.query_selector("a.next, li.next a, a[aria-label*='next'], a:has-text('Next')")
                    
                    # Verify if the Next button is present and visible
                    if next_button and await next_button.is_visible():
                        # Verify if the Next button is disabled (has 'disabled' class or 'aria-disabled')
                        is_disabled = await page.evaluate("""
                            (el) => {
                                if (el.classList.contains('disabled') || el.getAttribute('aria-disabled') === 'true') {
                                    return true;
                                }
                                const parent = el.closest('li');
                                if (parent && parent.classList.contains('disabled')) {
                                    return true;
                                }
                                return false;
                            }
                        """, next_button)
                        
                        if is_disabled:
                            logger.info("Pagination Next button is disabled. Reached the end of listings.")
                            break
                        else:
                            logger.info("Navigating to next page of results...")
                            await next_button.click()
                            # Wait for the DOM content to refresh
                            await page.wait_for_timeout(4000)
                            page_num += 1
                    else:
                        logger.info("No visible 'Next' pagination button found. Reached the end of listings.")
                        break
                        
            except Exception as e:
                logger.error(f"Failed to scrape Adobe Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Adobe Careers scrape. Found total {len(listings)} listings.")
        return listings
