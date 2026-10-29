import asyncio
import gc
import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class CventPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "cvent_careers"

    @property
    def portal_name(self) -> str:
        return "Cvent Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://careers.cvent.com/jobs?tags2=Technology&locations=Gurugram,,India&categories=Site%20Reliability%20Engineering|Software%20Development|Technology"
        logger.info("Navigating to Cvent Careers page to scrape listings.")
        
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
            
            page_num = 1
            max_pages = 20
            
            while page_num <= max_pages:
                url = f"{base_url}&page={page_num}"
                logger.info(f"Scraping Cvent Careers page {page_num}: {url}")
                
                await page.goto(url, wait_until="networkidle", timeout=35000)
                await page.wait_for_timeout(2000)
                
                links = await page.query_selector_all("a")
                page_listings_count = 0
                duplicate_found = False
                
                for link in links:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()
                    
                    if href and "/jobs/" in href and title:
                        href_clean = href.strip()
                        title_clean = title.strip().replace("\n", " ")
                        
                        if title_clean.lower() == "apply now" or not title_clean:
                            continue
                            
                        parts = href_clean.split("/")
                        jobid = ""
                        for p_item in parts:
                            if "?" in p_item:
                                p_item = p_item.split("?")[0]
                            if p_item.isdigit():
                                jobid = p_item
                                break
                                
                        if not jobid:
                            try:
                                job_idx = parts.index("jobs")
                                if job_idx + 1 < len(parts):
                                    possible_id = parts[job_idx + 1]
                                    if "?" in possible_id:
                                        possible_id = possible_id.split("?")[0]
                                    jobid = possible_id
                            except ValueError:
                                pass
                                
                        if jobid and title_clean:
                            if jobid in seen_ids:
                                duplicate_found = True
                                break
                                
                            seen_ids.add(jobid)
                            page_listings_count += 1
                            
                            if href_clean.startswith("http"):
                                job_listing_link = href_clean
                            else:
                                job_listing_link = f"https://careers.cvent.com{href_clean}"
                                
                            listings.append(
                                JobListing(
                                    jobid=jobid.strip(),
                                    role_name=title_clean,
                                    job_listing_link=job_listing_link,
                                    location="Gurugram, India",
                                )
                            )
                            
                if duplicate_found or page_listings_count == 0:
                    break
                    
                page_num += 1
                
        except Exception as e:
            logger.error(f"Failed to scrape Cvent Careers Portal: {e}", exc_info=True)
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
            
        logger.info(f"Finished Cvent Careers scrape. Found total {len(listings)} listings.")
        return listings
