import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class NielsenPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "nielsen_careers"

    @property
    def portal_name(self) -> str:
        return "Nielsen Careers (SmartRecruiters)"

    async def scrape(self) -> List[JobListing]:
        target_url = "https://careers.smartrecruiters.com/TheNielsenCompany/technology-jobs"
        logger.info(f"Navigating to Nielsen Careers (SmartRecruiters): {target_url}")
        
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
                
                await page.goto(target_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)
                
                # Auto-scroll and handle "Show more" buttons if present
                for _ in range(5):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1500)
                    
                    show_more = await page.query_selector("button:has-text('Show more'), a:has-text('Show more'), .js-more")
                    if show_more and await show_more.is_visible():
                        try:
                            await show_more.click()
                            await page.wait_for_timeout(1500)
                        except Exception:
                            pass
                            
                anchors = await page.query_selector_all("a[href*='jobs.smartrecruiters.com/TheNielsenCompany/']")
                logger.info(f"Found {len(anchors)} potential job anchors on Nielsen SmartRecruiters page.")
                
                for a in anchors:
                    href = await a.get_attribute("href")
                    if not href:
                        continue
                        
                    clean_url = href.split("?")[0].strip()
                    parts = clean_url.rstrip("/").split("/")
                    slug = parts[-1] if parts else ""
                    job_id = slug.split("-")[0] if "-" in slug else slug
                    
                    if not job_id or job_id in seen_ids:
                        continue
                        
                    h4 = await a.query_selector("h4")
                    if h4:
                        title = await h4.inner_text()
                    else:
                        title = await a.inner_text()
                        
                    title = title.strip()
                    if not title:
                        continue
                        
                    seen_ids.add(job_id)
                    listings.append(
                        JobListing(
                            jobid=job_id,
                            role_name=title,
                            job_listing_link=clean_url
                        )
                    )
                    
            except Exception as e:
                logger.error(f"Failed to scrape Nielsen Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Nielsen Careers scrape. Found total {len(listings)} listings.")
        return listings
