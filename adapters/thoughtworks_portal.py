import logging
import asyncio
import json
import urllib.request
import ssl
from typing import List
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ThoughtWorksPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "thoughtworks_careers"

    @property
    def portal_name(self) -> str:
        return "ThoughtWorks Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = "https://www.thoughtworks.com/rest/careers/jobs"
        listings = []
        
        try:
            def fetch_jobs():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                # Bypass strict cert validation as seen in other REST adapters
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    jobs = data.get("jobs", [])
                    
                    extracted = []
                    allowed_functions = {"Engineering & Technology", "Technology"}
                    
                    for j in jobs:
                        country = j.get("country", "")
                        funcs = j.get("jobFunctions", [])
                        
                        # Apply frontend filters: Country = India, Function = Engineering & Technology OR Technology
                        if country == "India" and any(f in allowed_functions for f in funcs):
                            job_id = j.get("sourceSystemId")
                            title = j.get("name")
                            
                            if job_id and title:
                                location = j.get("location", "India")
                                
                                extracted.append(JobListing(
                                    jobid=str(job_id),
                                    role_name=title,
                                    job_listing_link=f"https://www.thoughtworks.com/en-in/careers/jobs/{job_id}",
                                    location=location
                                ))
                    return extracted

            listings = await asyncio.to_thread(fetch_jobs)
            logger.info(f"Finished ThoughtWorks Careers scrape. Found total {len(listings)} listings.")
        except Exception as e:
            logger.error(f"Error scraping ThoughtWorks portal: {e}")
            
        return listings
