import logging
import asyncio
from typing import List
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class UberPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "uber_careers"

    @property
    def portal_name(self) -> str:
        return "Uber Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://jobs.uber.com/api/jobs/search/?countries=India&team=Engineer"
        listings = []
        page = 1
        
        try:
            # We use curl_cffi to bypass Cloudflare protection on the API endpoint natively
            async with AsyncSession(impersonate="chrome124") as s:
                while True:
                    url = f"{base_url}&page={page}"
                    
                    response = await s.get(url)
                    data = response.json()
                    
                    jobs = data.get("jobs", [])
                    if not jobs:
                        break
                        
                    for j in jobs:
                        job_id = j.get("Id")
                        title = j.get("Title")
                        
                        location = "India"
                        locations = j.get("Locations", [])
                        if locations and len(locations) > 0:
                            loc_data = locations[0]
                            city = loc_data.get("City", "")
                            location = city if city else "India"
                            
                        job_link = ""
                        urls = j.get("Urls", [])
                        if urls and len(urls) > 0:
                            job_link = "https://jobs.uber.com" + urls[0].get("Url", "")
                            
                        if not job_link:
                            job_link = f"https://jobs.uber.com/en/jobs/{job_id}/"
                            
                        if job_id and title:
                            listings.append(JobListing(
                                jobid=str(job_id),
                                role_name=title,
                                job_listing_link=job_link,
                                location=location
                            ))
                            
                    total_pages = data.get("totalPages", 1)
                    if page >= total_pages:
                        break
                        
                    page += 1
                    
                logger.info(f"Finished Uber Careers scrape. Found total {len(listings)} listings.")
        except Exception as e:
            logger.error(f"Error scraping Uber portal: {e}")
            
        return listings
