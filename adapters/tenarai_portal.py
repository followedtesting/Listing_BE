import logging
import asyncio
import json
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class TenaraiPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "tenarai_careers"

    @property
    def portal_name(self) -> str:
        return "Tenarai Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://career.tenarai.com/joblist"
        listings = []
        
        job_data = None
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                async def handle_response(response):
                    nonlocal job_data
                    if "get-job-list" in response.url:
                        try:
                            text = await response.text()
                            data = json.loads(text)
                            if data.get("success"):
                                job_data = data
                        except Exception as e:
                            pass
                            
                page.on("response", handle_response)
                
                logger.info(f"Navigating to {url}")
                await page.goto(url, wait_until="networkidle")
                await page.wait_for_timeout(2000)
                
                logger.info("Applying Experience filter: '0-2 Years'")
                await page.evaluate("""
                    let labels = document.querySelectorAll("label");
                    for (let l of labels) {
                        if (l.innerText.includes("0-2 Years")) {
                            l.click();
                            break;
                        }
                    }
                """)
                
                await page.wait_for_timeout(3000)
                
                if job_data:
                    jobs = job_data.get("data", {}).get("jobs", [])
                    for j in jobs:
                        job_id_full = j.get("JobIdFull")
                        title = j.get("Role")
                        location = j.get("displayLocation", "India")
                        
                        if job_id_full and title:
                            listings.append(JobListing(
                                jobid=str(job_id_full),
                                role_name=title,
                                job_listing_link=f"https://career.tenarai.com/job-description/{job_id_full}",
                                location=location
                            ))
                            
                await browser.close()
                logger.info(f"Finished Tenarai Careers scrape. Found total {len(listings)} listings.")
        except Exception as e:
            logger.error(f"Error scraping Tenarai portal: {e}")
            
        return listings
