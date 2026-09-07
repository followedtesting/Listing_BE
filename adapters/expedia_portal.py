import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing
import urllib.parse

logger = logging.getLogger(__name__)

class ExpediaPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "expedia_careers"

    @property
    def portal_name(self) -> str:
        return "Expedia Group Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://careers.expediagroup.com/jobs/?&filter[category]=Technology&filter[country]=India"
        logger.info(f"Navigating to Expedia Careers page to scrape listings.")
        
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
                    logger.info(f"Scraping Expedia Careers page {page_num}: {url}")
                    
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as nav_err:
                        logger.warning(f"Non-fatal navigation warning/timeout: {nav_err}")
                        
                    await page.wait_for_timeout(6000)  # Wait for JS to render job cards
                    
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and ("/job/" in href or "/jobs/" in href) and title:
                            href_clean = href.strip()
                            title_clean = title.strip().replace("\n", " ")
                            
                            # Skip common non-job links
                            if title_clean.lower() in ["apply", "apply now", "save job", "view job"]:
                                continue
                                
                            parts = href_clean.split("/")
                            jobid = ""
                            
                            # Usually Expedia jobs have format /jobs/12345/job-title or similar
                            for p_item in parts:
                                if "?" in p_item:
                                    p_item = p_item.split("?")[0]
                                if "R-" in p_item or "REQ-" in p_item or p_item.isdigit():
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
                                    # Normalize relative link
                                    if not href_clean.startswith("/"):
                                        href_clean = "/" + href_clean
                                    job_listing_link = f"https://careers.expediagroup.com{href_clean}"
                                    
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
                    
                    # Attempt click pagination first, fallback to URL iteration
                    next_btn = await page.query_selector("a.next, li.next a, button.next, a[aria-label*='Next']")
                    if next_btn and await next_btn.is_visible():
                        logger.info("Navigating via Next button...")
                        await next_btn.click()
                        await page.wait_for_timeout(6000)
                        
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape Expedia Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Expedia Careers scrape. Found total {len(listings)} listings.")
        return listings
