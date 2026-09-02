import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class OpenTextPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "opentext_careers"

    @property
    def portal_name(self) -> str:
        return "OpenText Careers"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://careers.opentext.com/us/en/search-results?category=Development&country=IND"
        logger.info(f"Navigating to OpenText Careers: {base_url}")
        
        listings: List[JobListing] = []
        seen_ids = set()
        from_param = 0
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                
                while True:
                    target_url = f"{base_url}&from={from_param}"
                    logger.info(f"Scraping OpenText offset from={from_param}...")
                    await page.goto(target_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)
                    
                    # Remove OneTrust cookie banner overlay if present
                    await page.evaluate("""
                        () => {
                            const ot = document.getElementById('onetrust-consent-sdk');
                            if (ot) ot.remove();
                            const backdrop = document.querySelector('.onetrust-pc-dark-filter');
                            if (backdrop) backdrop.remove();
                        }
                    """)
                    
                    job_cards = await page.evaluate("""
                        () => {
                            const links = Array.from(document.querySelectorAll('a[href*="/job/"]'));
                            const results = [];
                            for (const a of links) {
                                const href = a.href;
                                const title = a.innerText.trim();
                                if (href && title && title.length > 2 && !title.toLowerCase().includes('saved jobs')) {
                                    results.push({ title, href });
                                }
                            }
                            return results;
                        }
                    """)
                    
                    logger.info(f"Offset from={from_param}: rendered {len(job_cards)} job cards.")
                    
                    new_on_page = 0
                    for card in job_cards:
                        href = card["href"]
                        title = card["title"]
                        
                        parts = [p for p in href.split("/") if p]
                        job_id = ""
                        if "job" in parts:
                            idx = parts.index("job")
                            if idx + 1 < len(parts):
                                job_id = parts[idx + 1]
                        if not job_id:
                            job_id = parts[-1] if parts else title
                            
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            new_on_page += 1
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=href
                                )
                            )

                    if new_on_page == 0:
                        break
                        
                    from_param += 10
                    if from_param >= 200:  # safety cap
                        break

            except Exception as e:
                logger.error(f"Failed to scrape OpenText Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished OpenText Careers scrape. Found total {len(listings)} listings.")
        return listings
