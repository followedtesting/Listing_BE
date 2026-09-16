import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class TigerAnalyticsPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "tiger_analytics_careers"

    @property
    def portal_name(self) -> str:
        return "Tiger Analytics Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://www.tigeranalytics.com/about-us/current-openings/"
        logger.info(f"Navigating to Tiger Analytics Careers page to scrape listings.")
        
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
                
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)
                
                rows = await page.query_selector_all(".all-jobs-list-wrap")
                
                for row in rows:
                    location_elem = await row.query_selector(".jobs-location")
                    if not location_elem:
                        continue
                        
                    location_text = await location_elem.inner_text()
                    if "India" not in location_text:
                        continue
                        
                    title_elem = await row.query_selector(".jobs-title")
                    link_elem = await row.query_selector(".jobs-apply a")
                    
                    if not title_elem or not link_elem:
                        continue
                        
                    title = await title_elem.inner_text()
                    href = await link_elem.get_attribute("href")
                    
                    if title and href:
                        title_clean = title.strip()
                        href_clean = href.strip()
                        
                        # Extract ID from the end of the URL slug
                        # e.g., https://careers.tigeranalytics.com/#!/job-view/snowflake-dbt-architect-chennai-hyderabad-bangalore-202608121520498
                        parts = href_clean.split("-")
                        jobid = parts[-1]
                        
                        if "?" in jobid:
                            jobid = jobid.split("?")[0]
                            
                        if jobid and title_clean:
                            if jobid in seen_ids:
                                continue
                                
                            seen_ids.add(jobid)
                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title_clean,
                                    job_listing_link=href_clean
                                )
                            )
                            
            except Exception as e:
                logger.error(f"Failed to scrape Tiger Analytics Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Tiger Analytics Careers scrape. Found total {len(listings)} listings.")
        return listings
