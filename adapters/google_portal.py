import logging
import re
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class GooglePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "google_careers"

    @property
    def portal_name(self) -> str:
        return "Google Careers Portal"

    async def scrape(self) -> List[JobListing]:
        # User explicitly requested this exact URL scheme
        base_url = "https://www.google.com/about/careers/applications/jobs/results?q=%22Software%20Engineer%22&target_level=EARLY"
        logger.info(f"Navigating to Google Careers page to scrape listings.")
        
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
                    logger.info(f"Scraping Google Careers page {page_num}: {url}")
                    
                    try:
                        await page.goto(url, wait_until="networkidle", timeout=45000)
                    except Exception as nav_err:
                        logger.warning(f"Non-fatal navigation warning/timeout: {nav_err}")
                        
                    await page.wait_for_timeout(5000)
                    
                    # Extract jobs via page evaluate to easily parse jsdata
                    jobs_data = await page.evaluate("""() => {
                        let items = [];
                        let headers = document.querySelectorAll("h3.QJPWVe");
                        for (let h of headers) {
                            let parent = h.closest("li.lLd3Je");
                            if (parent) {
                                let div = parent.querySelector("div[jsdata]");
                                let jsdata = div ? div.getAttribute("jsdata") : "";
                                items.push({
                                    title: h.innerText,
                                    jsdata: jsdata
                                });
                            }
                        }
                        return items;
                    }""")
                    
                    if not jobs_data:
                        logger.info(f"No jobs found on page {page_num}. Terminating pagination.")
                        break
                        
                    page_listings_count = 0
                    
                    for job in jobs_data:
                        title_clean = job.get("title", "").strip()
                        jsdata = job.get("jsdata", "")
                        
                        # Parse job ID from jsdata: "Aiqs8c;111182182432547526;$2"
                        jobid = None
                        if jsdata:
                            parts = jsdata.split(";")
                            if len(parts) >= 2:
                                jobid = parts[1].strip()
                        
                        if not jobid:
                            # Fallback: Maybe we can extract ID using a regex if it's stored differently
                            match = re.search(r';(\d+);', jsdata)
                            if match:
                                jobid = match.group(1)
                                
                        if jobid and title_clean:
                            if jobid in seen_ids:
                                continue
                                
                            seen_ids.add(jobid)
                            page_listings_count += 1
                            
                            job_listing_link = f"https://www.google.com/about/careers/applications/jobs/results/{jobid}"
                            
                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title_clean,
                                    job_listing_link=job_listing_link
                                )
                            )
                            
                    logger.info(f"Found {page_listings_count} new job postings on page {page_num}.")
                    
                    if page_listings_count == 0:
                        logger.info("No new distinct listings found, terminating pagination.")
                        break
                        
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape Google Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Google Careers scrape. Found total {len(listings)} listings.")
        return listings
