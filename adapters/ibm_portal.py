import logging
import urllib.parse
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class IBMPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "ibm_careers"

    @property
    def portal_name(self) -> str:
        return "IBM Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://www.ibm.com/in-en/careers/search?field_keyword_08[0]=Software%20Engineering&field_keyword_05[0]=India"
        logger.info(f"Navigating to IBM Careers page to scrape listings.")
        
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
                
                try:
                    await page.goto(base_url, wait_until="domcontentloaded", timeout=45000)
                except Exception as nav_err:
                    logger.warning(f"Non-fatal navigation warning/timeout: {nav_err}")
                    
                await page.wait_for_timeout(5000)
                
                page_num = 1
                max_pages = 20
                
                while page_num <= max_pages:
                    logger.info(f"Scraping IBM Careers page {page_num}")
                    
                    links = await page.query_selector_all("a")
                    page_listings_count = 0
                    
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        
                        if href and title and "jobId=" in href:
                            # Extract Job ID from URL parameters
                            href_clean = href.strip()
                            parsed_url = urllib.parse.urlparse(href_clean)
                            qs = urllib.parse.parse_qs(parsed_url.query)
                            
                            jobid = qs.get("jobId", [""])[0]
                            
                            # Clean up title: IBM usually formats as Category\nTitle\nLevel\nLocation
                            lines = [line.strip() for line in title.split("\n") if line.strip()]
                            if len(lines) > 1:
                                title_clean = lines[1]  # The second line is usually the title
                            else:
                                title_clean = " ".join(lines)
                                
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
                                    job_listing_link = f"https://careers.ibm.com{href_clean}"
                                    
                                listings.append(
                                    JobListing(
                                        jobid=jobid.strip(),
                                        role_name=title_clean,
                                        job_listing_link=job_listing_link
                                    )
                                )
                                
                    if page_listings_count == 0:
                        logger.info("Reached end of distinct listings or no jobs found.")
                        break
                        
                    logger.info(f"Found {page_listings_count} job postings on page {page_num}.")
                    
                    # Attempt click pagination via JS
                    next_clicked = await page.evaluate("""() => {
                        let nextBtn = document.querySelector("li.pager__item--next a, a[title='Go to next page'], a.next, button.next, [aria-label*='Next'], [aria-label*='next']");
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
                logger.error(f"Failed to scrape IBM Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished IBM Careers scrape. Found total {len(listings)} listings.")
        return listings
