import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class BarclaysPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "barclays_careers"

    @property
    def portal_name(self) -> str:
        return "Barclays Careers"

    async def scrape(self) -> List[JobListing]:
        logger.info("Navigating to Barclays Careers (Development & Engineering - India)...")
        
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
                max_pages = 25
                india_cities = ["/noida/", "/pune/", "/mumbai/", "/bengaluru/", "/chennai/", "/hyderabad/", "/gurgaon/", "/india/"]
                
                while page_num <= max_pages:
                    url = f"https://search.jobs.barclays/search-jobs?ac=79683&orgIds=13015&l=India&c=Development%20and%20Engineering&p={page_num}"
                    logger.info(f"Fetching Barclays Careers page {page_num}: {url}")
                    
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(1500)
                    
                    # Remove potential overlay banners
                    await page.evaluate("""() => {
                        const alert = document.getElementById('system-ialert');
                        if (alert) alert.remove();
                        const ot = document.getElementById('onetrust-consent-sdk');
                        if (ot) ot.remove();
                    }""")
                    
                    cards = await page.query_selector_all(".job-list--card .list-item, section#search-results-list li")
                    if not cards:
                        logger.info(f"No job cards found on Barclays page {page_num}. Stopping pagination.")
                        break
                        
                    page_added = 0
                    for card in cards:
                        anchor = await card.query_selector("a[href*='/job/']")
                        if not anchor:
                            continue
                            
                        href = await anchor.get_attribute("href")
                        if not href or "/job/" not in href:
                            continue
                            
                        parts = href.rstrip("/").split("/")
                        job_id = parts[-1] if parts else ""
                        if not job_id or job_id in seen_ids:
                            continue
                            
                        card_text = (await card.inner_text()).lower()
                        href_lower = href.lower()
                        
                        # Validate that position is located in India
                        is_india = "india" in card_text or any(city in href_lower for city in india_cities)
                        if not is_india:
                            continue
                            
                        h2 = await card.query_selector("h2, h3, .search-results-job-title")
                        title = await h2.inner_text() if h2 else await anchor.inner_text()
                        title = title.strip()
                        if not title:
                            continue
                            
                        seen_ids.add(job_id)
                        full_link = f"https://search.jobs.barclays{href}" if href.startswith("/") else href
                        
                        listings.append(
                            JobListing(
                                jobid=job_id,
                                role_name=title,
                                job_listing_link=full_link
                            )
                        )
                        page_added += 1
                        
                    logger.info(f"Scraped {page_added} India Development & Engineering jobs from Barclays page {page_num}.")
                    
                    if page_added == 0:
                        logger.info(f"0 new India jobs found on page {page_num}. Ending pagination.")
                        break
                        
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape Barclays Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Barclays Careers scrape. Found total {len(listings)} listings.")
        return listings
