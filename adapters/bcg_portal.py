import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing
import urllib.parse

logger = logging.getLogger(__name__)

class BCGPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "bcg_careers"

    @property
    def portal_name(self) -> str:
        return "BCG Careers Portal"

    async def scrape(self) -> List[JobListing]:
        # Using query parameters that PhenomPeople usually accepts
        base_url = "https://careers.bcg.com/global/en/search-results?category=Technology%20and%20Engineering&country=India"
        logger.info(f"Navigating to BCG Careers page to scrape listings.")
        
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
                
                # Navigate
                try:
                    await page.goto(base_url, wait_until="domcontentloaded", timeout=45000)
                except Exception as nav_err:
                    logger.warning(f"Non-fatal navigation warning/timeout: {nav_err}")
                    
                await page.wait_for_timeout(5000)
                
                # Click the filters via JavaScript to entirely bypass cookie overlays or intercepts
                try:
                    logger.info("Applying Category filter via JS...")
                    await page.evaluate("""() => {
                        let labels = Array.from(document.querySelectorAll('label'));
                        let tech = labels.find(l => l.innerText.includes('Technology and Engineering'));
                        if (tech) tech.click();
                    }""")
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning(f"Could not select Category filter: {e}")

                try:
                    logger.info("Applying Country filter via JS...")
                    await page.evaluate("""() => {
                        let labels = Array.from(document.querySelectorAll('label'));
                        let india = labels.find(l => l.innerText.includes('India'));
                        if (india) india.click();
                    }""")
                    await page.wait_for_timeout(4000)
                except Exception as e:
                    logger.warning(f"Could not select Country filter: {e}")
                
                # Check for pagination
                page_num = 1
                max_pages = 20
                
                while page_num <= max_pages:
                    logger.info(f"Scraping BCG Careers page {page_num}")
                    
                    # Instead of relying on URL parameter changes for SPA, we extract links
                    # then click the "Next" button.
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and title and "/job/" in href.lower():
                            href_clean = href.strip()
                            title_clean = title.strip().replace("\n", " ")
                            
                            # Skip common Phenom non-job links
                            if title_clean.isdigit() or title_clean.lower() in ["next", "saved jobs", "jobs", "clear filters", "apply", "save job"]:
                                continue
                                
                            parts = href_clean.split("/")
                            jobid = ""
                            
                            # Usually BCG jobs have format /job/REQ12345/job-title or similar
                            for p_item in parts:
                                if "?" in p_item:
                                    p_item = p_item.split("?")[0]
                                if "REQ" in p_item.upper() or p_item.isdigit():
                                    jobid = p_item
                                    break
                                    
                            if not jobid:
                                jobid = parts[-2] if parts[-1] == "" else parts[-1]
                                
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
                                    job_listing_link = f"https://careers.bcg.com{href_clean}"
                                    
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
                    
                    # Attempt click pagination via JS
                    next_clicked = await page.evaluate("""() => {
                        let nextBtn = document.querySelector("a.next, li.next a, button.next, a[aria-label*='Next']");
                        if (nextBtn && nextBtn.style.display !== 'none' && !nextBtn.className.includes('disabled')) {
                            nextBtn.click();
                            return true;
                        }
                        return false;
                    }""")
                    
                    if next_clicked:
                        logger.info("Navigating via Next button (JS)...")
                        await page.wait_for_timeout(6000)
                        page_num += 1
                    else:
                        break
                    
            except Exception as e:
                logger.error(f"Failed to scrape BCG Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished BCG Careers scrape. Found total {len(listings)} listings.")
        return listings
