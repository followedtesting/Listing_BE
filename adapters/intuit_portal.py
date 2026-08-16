import logging
import re
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class IntuitPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "intuit_careers"

    @property
    def portal_name(self) -> str:
        return "Intuit Careers"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://jobs.intuit.com/search-jobs/India/27595/2/1269750/0/0/100"
        logger.info(f"Navigating to Intuit Careers: {base_url}/1")
        
        listings: List[JobListing] = []
        seen_ids = set()
        page_num = 1
        
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
                    url = f"{base_url}/{page_num}"
                    logger.info(f"Fetching Intuit Careers page {page_num}: {url}")
                    
                    res = await page.goto(url, wait_until="domcontentloaded")
                    if not res or res.status != 200:
                        logger.warning(f"Intuit page {page_num} returned status {res.status if res else 'None'}. Ending pagination.")
                        break
                        
                    await page.wait_for_timeout(2000)
                    
                    job_cards = await page.evaluate("""
                        () => {
                            const cards = Array.from(document.querySelectorAll("#search-results list li, #search-results li, ul.search-results-list li, section#search-results li"));
                            return cards.map(li => {
                                const a = li.querySelector("a[href*='/job/']");
                                const locEl = li.querySelector(".job-location, .location");
                                return {
                                    href: a ? a.getAttribute('href') : null,
                                    title: a ? a.innerText.trim().replace(/\\n/g, ' ') : null,
                                    location: locEl ? locEl.innerText.trim().replace(/\\n/g, ' ') : ''
                                };
                            }).filter(c => c.href && c.title);
                        }
                    """)
                    
                    if not job_cards:
                        break
                        
                    new_on_page = 0
                    for card in job_cards:
                        href = card["href"]
                        title = card["title"]
                        loc = card["location"]
                        
                        match = re.search(r"/(\d+)$", href)
                        job_id = match.group(1) if match else href
                        
                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            new_on_page += 1
                            
                            # Verify location is India / Bangalore / Bengaluru
                            is_india = any(k in href.lower() or k in loc.lower() or k in title.lower() for k in ["india", "bengaluru", "bangalore"])
                            
                            # Verify Software Engineering / technical role
                            title_lower = title.lower()
                            tech_keywords = ["software", "engineer", "developer", "architect", "tech", "data engineer", "frontend", "backend", "fullstack", "full stack", "mobile", "ios", "android", "platform"]
                            non_tech_keywords = ["product designer", "tax", "accountant", "facilitator", "recruiter", "program manager", "vendor partner", "business data analyst"]
                            
                            is_tech = any(k in title_lower for k in tech_keywords) and not any(nk in title_lower for nk in non_tech_keywords)
                            
                            if is_india and is_tech:
                                full_link = href if href.startswith("http") else f"https://jobs.intuit.com{href}"
                                listings.append(
                                    JobListing(
                                        jobid=job_id,
                                        role_name=title,
                                        job_listing_link=full_link
                                    )
                                )

                    if new_on_page == 0 or page_num >= 5:
                        break
                        
                    page_num += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape Intuit Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Intuit Careers scrape. Found total {len(listings)} listings.")
        return listings
