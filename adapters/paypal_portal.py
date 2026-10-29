import asyncio
import gc
import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class PaypalPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "paypal_careers"

    @property
    def portal_name(self) -> str:
        return "PayPal Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://paypal.eightfold.ai/careers?domain=paypal.com&location=india"
        logger.info("Navigating to PayPal Eightfold page to scrape listings.")
        
        listings: List[JobListing] = []
        seen_ids = set()
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
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            # Abort heavy assets
            await page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,mp4,webm}",
                lambda route: route.abort()
            )
            
            start_index = 0
            max_pages = 20
            limit = 10
            
            while start_index < (max_pages * limit):
                url = f"{base_url}&start={start_index}"
                logger.info(f"Scraping PayPal Careers page at start={start_index}: {url}")
                
                try:
                    await page.goto(url, wait_until="networkidle", timeout=35000)
                except Exception as nav_err:
                    logger.warning(f"Non-fatal navigation warning/timeout: {nav_err}")
                    
                await page.wait_for_timeout(2000)
                
                links = await page.query_selector_all("a")
                page_listings_count = 0
                
                for link in links:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()
                    
                    if href and title and "/careers/job/" in href.lower():
                        href_clean = href.strip()
                        raw_text = title.strip().replace("\n", " | ")
                        parts = raw_text.split(" | ")
                        title_clean = parts[0].strip() if parts else raw_text
                        
                        parts_href = href_clean.split("?")[0].split("/")
                        jobid = parts_href[-1]
                        
                        if jobid and title_clean:
                            if "india" not in raw_text.lower():
                                continue
                                
                            if jobid in seen_ids:
                                continue
                                
                            seen_ids.add(jobid)
                            page_listings_count += 1
                            
                            if href_clean.startswith("http"):
                                job_listing_link = href_clean
                            else:
                                if not href_clean.startswith("/"):
                                    href_clean = "/" + href_clean
                                job_listing_link = f"https://paypal.eightfold.ai{href_clean}"
                                
                            listings.append(
                                JobListing(
                                    jobid=jobid.strip(),
                                    role_name=title_clean,
                                    job_listing_link=job_listing_link,
                                    location="India",
                                )
                            )
                            
                if page_listings_count == 0:
                    break
                    
                start_index += limit
                
        except Exception as e:
            logger.error(f"Failed to scrape PayPal Careers Portal: {e}", exc_info=True)
            raise
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
            
        logger.info(f"Finished PayPal Careers scrape. Found total {len(listings)} listings.")
        return listings
