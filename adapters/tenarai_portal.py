import logging
import asyncio
import gc
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
        playwright_obj = None
        browser = None
        
        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                    "--disable-extensions",
                    "--js-flags=--max-old-space-size=128",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page = await context.new_page()
            
            # Abort heavy assets
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,mp4,webm}",
                lambda route: route.abort()
            )
            
            async def handle_response(response):
                nonlocal job_data
                if "get-job-list" in response.url:
                    try:
                        text = await response.text()
                        data = json.loads(text)
                        if data.get("success"):
                            job_data = data
                    except Exception:
                        pass
                        
            page.on("response", handle_response)
            
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=30000)
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
                        
            logger.info(f"Finished Tenarai Careers scrape. Found total {len(listings)} listings.")
        except Exception as e:
            logger.error(f"Error scraping Tenarai portal: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_obj:
                try:
                    await playwright_obj.stop()
                except Exception:
                    pass
            gc.collect()
            
        return listings
