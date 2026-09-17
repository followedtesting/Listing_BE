import json
import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class USTPortalAdapter(BaseJobAdapter):
    @property
    def portal_name(self) -> str:
        return "UST Careers"
        
    @property
    def portal_id(self) -> str:
        return "ust_careers"
        
    async def scrape(self) -> List[JobListing]:
        url = "https://www.ust.com/en/jobsearch"
        token = None
        
        # We must use stealth to bypass Cloudflare and intercept the Coveo API token
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                
                from playwright_stealth import Stealth
                await Stealth().apply_stealth_async(page)
                
                # Setup request interception to grab the token
                def handle_request(request):
                    nonlocal token
                    if "search/v2" in request.url and "coveo.com" in request.url:
                        auth_header = request.headers.get("authorization")
                        if auth_header:
                            token = auth_header
                            
                page.on("request", handle_request)
                
                logger.info(f"Navigating to {url} to fetch Coveo token...")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Wait until token is captured or timeout
                for _ in range(30):
                    if token:
                        break
                    await page.wait_for_timeout(1000)
                    
            except Exception as e:
                logger.error(f"Error fetching UST token: {e}")
            finally:
                await browser.close()
                
        if not token:
            logger.error("Failed to capture Coveo token from UST portal.")
            return []
            
        logger.info("Successfully captured Coveo token. Fetching jobs via API...")
        
        # Now fetch the jobs using aiohttp and the token
        coveo_url = "https://ustglobalproduction4ggrtx7v.org.coveo.com/rest/search/v2?organizationId=ustglobalproduction4ggrtx7v"
        headers = {
            "authorization": token,
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0"
        }
        payload = {
            "aq": '@source=="rippleHire-api" AND @country=="India" AND (@exprangeinyears=="0 - 2" OR @exprangeinyears=="1 - 3")',
            "numberOfResults": 1000,
            "firstResult": 0
        }
        
        listings = []
        async with async_playwright() as p:
            api_context = await p.request.new_context(ignore_https_errors=True)
            resp = await api_context.post(coveo_url, headers=headers, data=payload)
            if resp.status == 200:
                data = await resp.json()
                results = data.get("results", [])
                for item in results:
                    raw = item.get("raw", {})
                    title = raw.get("jobtitle", "Unknown Role")
                    job_url = raw.get("clickableuri", "")
                    req_id = raw.get("externalcode", "")
                    
                    location = "India"
                    if raw.get("city"):
                        if isinstance(raw["city"], list) and len(raw["city"]) > 0:
                            location = f"{raw['city'][0]}, {location}"
                        elif isinstance(raw["city"], str):
                            location = f"{raw['city']}, {location}"
                            
                    listings.append(
                        JobListing(
                            role_name=title,
                            job_listing_link=job_url,
                            location=location,
                            jobid=req_id
                        )
                    )
            else:
                logger.error(f"UST API returned status {resp.status}")
                    
        return listings
