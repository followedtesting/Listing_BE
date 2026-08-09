import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NutanixPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "nutanix_careers"

    @property
    def portal_name(self) -> str:
        return "Nutanix Careers"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://careers.nutanix.com/en/jobs/?search=&country=India&team=Engineering&pagesize=100#results"
        logger.info(f"Navigating to Nutanix Careers: {target_url}")
        
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
                
                await page.goto(target_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(4000)
                
                anchors = await page.query_selector_all("a[href*='/jobs/']")
                logger.info(f"Found {len(anchors)} job candidate anchors on Nutanix Careers DOM.")
                
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    text = await a.inner_text() or ""
                    title = text.strip().replace("\n", " ")
                    
                    if not href or href.rstrip("/") in ["/en/jobs", "/jobs", "/en/jobs/saved-jobs", "/en/jobs/#results", "https://careers.nutanix.com/en/jobs/"]:
                        continue
                        
                    parts = [p for p in href.rstrip("/").split("/") if p]
                    
                    job_id = None
                    for p in parts:
                        if p.isdigit() or (p.startswith("n") and p[1:].isdigit()):
                            job_id = p
                            break
                            
                    if not job_id and len(parts) >= 2:
                        job_id = parts[-2]
                        
                    if job_id and job_id not in ["en", "jobs", "saved-jobs", "#results"] and title and job_id not in seen_ids:
                        seen_ids.add(job_id)
                        full_link = href if href.startswith("http") else f"https://careers.nutanix.com{href}"
                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=full_link
                            )
                        )
                        
            except Exception as e:
                logger.error(f"Failed to scrape Nutanix Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Nutanix Careers scrape. Found total {len(listings)} listings.")
        return listings
