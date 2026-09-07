import logging
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing
import urllib.parse

logger = logging.getLogger(__name__)

class InnovaccerPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "innovaccer_careers"

    @property
    def portal_name(self) -> str:
        return "Innovaccer Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://innovaccer.com/careers/jobs"
        logger.info(f"Navigating to Innovaccer Careers page.")
        
        listings: List[JobListing] = []
        seen_ids = set()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(5000)
                
                # Expand "Department" dropdown and select "Engineering and analytics"
                try:
                    logger.info("Applying Department filter...")
                    dept_dropdown = await page.query_selector("text='Department'")
                    if dept_dropdown:
                        await dept_dropdown.click()
                        await page.wait_for_timeout(1000)
                        dept_option = await page.query_selector("text='Engineering and analytics'")
                        if dept_option:
                            await dept_option.click()
                        await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning(f"Could not select Department filter: {e}")
                    
                # Expand "Location" dropdown and select "India, Uttar Pradesh, Noida"
                try:
                    logger.info("Applying Location filter...")
                    loc_dropdown = await page.query_selector("text='Location'")
                    if loc_dropdown:
                        await loc_dropdown.click()
                        await page.wait_for_timeout(1000)
                        loc_option = await page.query_selector("text='India, Uttar Pradesh, Noida'")
                        if loc_option:
                            await loc_option.click()
                        await page.wait_for_timeout(3000)
                except Exception as e:
                    logger.warning(f"Could not select Location filter: {e}")
                    
                # Handle "SHOW MORE" pagination
                logger.info("Checking for SHOW MORE buttons...")
                while True:
                    show_more = await page.query_selector("text='SHOW MORE'")
                    if show_more and await show_more.is_visible():
                        try:
                            await show_more.click()
                            await page.wait_for_timeout(2000)
                        except Exception:
                            break
                    else:
                        break
                        
                # Fetch all links. Usually job links look like apply.workable.com/j/...
                logger.info("Parsing job links...")
                links = await page.query_selector_all("a")
                for link in links:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()
                    
                    if href and title and "workable.com/j/" in href:
                        title_clean = title.strip().replace("\n", " ")
                        href_clean = href.strip()
                        
                        # extract jobid from workable link (e.g. https://apply.workable.com/j/47D6179483)
                        jobid = href_clean.split("/")[-1]
                            
                        if jobid and title_clean and len(title_clean) > 3:
                            if jobid in seen_ids:
                                continue
                                
                            seen_ids.add(jobid)
                            
                            listings.append(
                                JobListing(
                                    jobid=jobid.strip(),
                                    role_name=title_clean,
                                    job_listing_link=href_clean
                                )
                            )
                            
            except Exception as e:
                logger.error(f"Failed to scrape Innovaccer Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Innovaccer Careers scrape. Found total {len(listings)} listings.")
        return listings
