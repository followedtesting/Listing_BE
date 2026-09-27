import logging
import asyncio
import re
from typing import List
from urllib.parse import urljoin
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class TeradataPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "teradata_careers"

    @property
    def portal_name(self) -> str:
        return "Teradata Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://careers.teradata.com/jobs?location=Hyderabad%2C+India&location=Bengaluru%2C+India&location=Pune%2C+India&location=Bangalore+-+Virtual%2C+India&location=Airoli+Navi+Mumbai%2C+India&location=Mumbai%2C+India&location=Navi+Mumbai%2C+India&location=India&jobCategory=3"
        listings = []
        seen_ids = set()
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                
                jobs = await page.locator("a[href*=\"/jobs/\"]").all()
                for j in jobs:
                    href = await j.get_attribute("href")
                    if not href:
                        continue
                        
                    text = await j.inner_text()
                    lines = [t.strip() for t in text.split("\n") if t.strip()]
                    title = lines[0] if lines else "Unknown Role"
                    
                    match = re.search(r"/jobs/(\d+)/", href)
                    job_id = match.group(1) if match else ""
                    if not job_id or job_id in seen_ids:
                        continue
                        
                    seen_ids.add(job_id)
                    title = re.sub(rf"\s*-\s*{job_id}$", "", title).strip()
                        
                    job_link = urljoin("https://careers.teradata.com", href)
                    
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=job_link,
                            location="India"
                        )
                    )
                    
                await browser.close()
                logger.info(f"Finished Teradata Careers scrape. Found total {len(listings)} listings.")
        except Exception as e:
            logger.error(f"Error scraping Teradata portal: {e}")
            
        return listings
