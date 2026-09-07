import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing
import urllib.parse

logger = logging.getLogger(__name__)

class WellsFargoPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "wellsfargo_careers"

    @property
    def portal_name(self) -> str:
        return "Wells Fargo Careers Portal"

    async def scrape(self) -> List[JobListing]:
        # Using the base query URL without page
        base_url = "https://www.wellsfargojobs.com/en/jobs/?country=India&team=Technology&pagesize=50"
        logger.info(f"Navigating to Wells Fargo Careers page to scrape listings.")
        
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
                    url = f"{base_url}&page={page_num}#results"
                    logger.info(f"Scraping Wells Fargo Careers page {page_num}: {url}")
                    
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
                        
                        if href and "/jobs/" in href and title:
                            href_clean = href.strip()
                            title_clean = title.strip().replace("\n", " ")
                            
                            title_lower = title_clean.lower()
                            # Skip pagination links and other non-job links
                            if title_clean.isdigit() or "saved jobs" in title_lower or title_lower in ["next", "jobs", "clear filters", "apply", "save job", "1", "2", "3", "4", "5"]:
                                continue
                                
                            parts = href_clean.split("/")
                            jobid = ""
                            
                            for p_item in parts:
                                if "?" in p_item:
                                    p_item = p_item.split("?")[0]
                                if p_item.lower().startswith("r-") or p_item.lower().startswith("req") or p_item.isdigit():
                                    jobid = p_item
                                    break
                                    
                            if not jobid:
                                try:
                                    for kw in ["job", "jobs"]:
                                        if kw in parts:
                                            job_idx = parts.index(kw)
                                            if job_idx + 1 < len(parts):
                                                possible_id = parts[job_idx + 1]
                                                if "?" in possible_id:
                                                    possible_id = possible_id.split("?")[0]
                                                jobid = possible_id
                                                break
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
                                    if not href_clean.startswith("/"):
                                        href_clean = "/" + href_clean
                                    job_listing_link = f"https://www.wellsfargojobs.com{href_clean}"
                                    
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
                    
                    next_btn = await page.query_selector("a[aria-label*='Next'], li.next a, button.next, a:has-text('Next')")
                    if next_btn and await next_btn.is_visible():
                        logger.info("Next button found, moving to next page.")
                        page_num += 1
                    else:
                        logger.info("No more pages available via Next button.")
                        if page_listings_count < 50:
                            break
                        page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape Wells Fargo Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Wells Fargo Careers scrape. Found total {len(listings)} listings.")
        return listings
