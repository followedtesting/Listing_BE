import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ApplePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "apple_careers"

    @property
    def portal_name(self) -> str:
        return "Apple Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://jobs.apple.com/en-in/search?location=india-INDC&team=apps-and-frameworks-SFTWR-AF+machine-learning-SFTWR-MCHLN+core-operating-systems-SFTWR-COS"
        logger.info(f"Navigating to Apple Careers page: {url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                # Use standard Chrome User-Agent and desktop viewport to bypass any bot protections
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                )
                page = await context.new_page()
                
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as nav_err:
                    logger.warning(f"Non-fatal navigation warning/timeout: {nav_err}")
                
                # Allow a short delay for content hydration
                await page.wait_for_timeout(6000)
                
                page_num = 1
                max_pages = 10  # Safeguard cap
                
                while page_num <= max_pages:
                    logger.info(f"Scraping Apple Careers page {page_num}...")
                    
                    # Fetch all visible links in the DOM
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and "/details/" in href.lower():
                            title_clean = title.strip()
                            # Skip description buttons or metadata links
                            if not title_clean or title_clean.lower() == "see full role description":
                                continue
                                
                            parts = href.strip().split("/")
                            # Apple pattern: /en-in/details/[REQ_ID]/[SLUG]
                            # Example: /en-in/details/200670839-0321/database-reliability-engineer...
                            jobid = ""
                            try:
                                details_idx = parts.index("details")
                                if details_idx + 1 < len(parts):
                                    jobid = parts[details_idx + 1]
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
                                if href.startswith("http"):
                                    job_listing_link = href.strip()
                                else:
                                    job_listing_link = f"https://jobs.apple.com{href.strip()}"
                                    
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
                    
                    # Locate the "Next Page" button
                    next_button = await page.query_selector("button:has-text('Next Page'), button[aria-label='Next Page'], button.icon-chevronend")
                    
                    # Verify if Next button is visible
                    if next_button and await next_button.is_visible():
                        is_disabled = await page.evaluate("""
                            (btn) => {
                                if (btn.disabled || btn.classList.contains('disabled') || btn.getAttribute('aria-disabled') === 'true') {
                                    return true;
                                }
                                const parent = btn.closest('li');
                                if (parent && (parent.classList.contains('disabled') || parent.classList.contains('pagination-disabled'))) {
                                    return true;
                                }
                                return false;
                            }
                        """, next_button)
                        
                        if is_disabled:
                            logger.info("Pagination Next Page button is disabled. Reached the end of listings.")
                            break
                        else:
                            logger.info("Navigating to next page of results...")
                            await next_button.click()
                            # Wait for DOM content to refresh
                            await page.wait_for_timeout(6000)
                            page_num += 1
                    else:
                        logger.info("No visible 'Next Page' pagination button found. Reached the end of listings.")
                        break
                        
            except Exception as e:
                logger.error(f"Failed to scrape Apple Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Apple Careers scrape. Found total {len(listings)} listings.")
        return listings
