import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class BakerHughesPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "bakerhughes_careers"

    @property
    def portal_name(self) -> str:
        return "Baker Hughes Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://careers.bakerhughes.com/global/en/search-results?qcountry=India"
        logger.info(f"Navigating to Baker Hughes Careers page to scrape listings.")
        
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
                
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(6000)
                
                # Expand filters if necessary (sometimes they are folded, but JS querySelectorAll works anyway)
                logger.info("Applying Digital Technology filter via JS...")
                await page.evaluate("""() => {
                    let labels = Array.from(document.querySelectorAll('label'));
                    let digital = labels.find(l => l.innerText.includes('Digital Technology'));
                    if (digital) digital.click();
                }""")
                await page.wait_for_timeout(3000)
                
                logger.info("Applying Engineering/Technology filter via JS...")
                await page.evaluate("""() => {
                    let labels = Array.from(document.querySelectorAll('label'));
                    let eng = labels.find(l => l.innerText.includes('Engineering/Technology'));
                    if (eng) eng.click();
                }""")
                await page.wait_for_timeout(5000)
                
                page_num = 1
                max_pages = 20
                
                while page_num <= max_pages:
                    logger.info(f"Scraping Baker Hughes page {page_num}")
                    
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and title and "/job/" in href.lower():
                            href_clean = href.strip()
                            title_clean = title.strip().replace("\n", " ")
                            
                            # ID extraction: e.g. /global/en/job/R161330/Cyber-Security...
                            parts = href_clean.split("/")
                            jobid = None
                            for i, part in enumerate(parts):
                                if part.lower() == "job" and i + 1 < len(parts):
                                    jobid = parts[i + 1]
                                    break
                            
                            if jobid and "?" in jobid:
                                jobid = jobid.split("?")[0]
                                
                            if jobid and title_clean:
                                if jobid in seen_ids:
                                    continue
                                    
                                seen_ids.add(jobid)
                                page_listings_count += 1
                                
                                if href_clean.startswith("http"):
                                    job_listing_link = href_clean
                                else:
                                    if not href_clean.startswith("/"):
                                        href_clean = "/" + href_clean
                                    job_listing_link = f"https://careers.bakerhughes.com{href_clean}"
                                    
                                listings.append(
                                    JobListing(
                                        jobid=jobid,
                                        role_name=title_clean,
                                        job_listing_link=job_listing_link
                                    )
                                )
                                
                    if page_listings_count == 0:
                        logger.info("Reached end of distinct listings or no jobs found.")
                        break
                        
                    logger.info(f"Found {page_listings_count} job postings on page {page_num}.")
                    
                    # Next button pagination via JS
                    next_clicked = await page.evaluate("""() => {
                        let nextBtn = document.querySelector("a[aria-label*='next'], a[aria-label*='Next']");
                        if (nextBtn && nextBtn.style.display !== 'none' && !nextBtn.className.includes('disabled') && !nextBtn.parentElement.className.includes('disabled')) {
                            nextBtn.click();
                            return true;
                        }
                        return false;
                    }""")
                    
                    if next_clicked:
                        logger.info("Navigating via Next button (JS)...")
                        await page.wait_for_timeout(6000)
                        page_num += 1
                    else:
                        logger.info("No next button found. Terminating pagination.")
                        break
                    
            except Exception as e:
                logger.error(f"Failed to scrape Baker Hughes Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Baker Hughes Careers scrape. Found total {len(listings)} listings.")
        return listings
