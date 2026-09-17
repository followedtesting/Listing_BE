import logging
import asyncio
from typing import List
from curl_cffi import requests
from urllib.parse import urljoin
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class BainPortalAdapter(BaseJobAdapter):
    @property
    def portal_name(self) -> str:
        return "Bain & Company"
        
    @property
    def portal_id(self) -> str:
        return "bain"
        
    async def scrape(self) -> List[JobListing]:
        url_html = "https://www.bain.com/careers/find-a-role/?filters=workareas(1831447)|offices(274,275,276)|"
        url_api = "https://www.bain.com/en/api/jobsearch/keyword/get?start=0&results=1000&filters=workareas(1831447)|offices(274,275,276)|&searchValue="
        
        listings = []
        try:
            # We must use curl_cffi to bypass Cloudflare
            def fetch_jobs():
                session = requests.Session(impersonate="chrome110")
                session.headers.update({
                    "Accept": "application/json, text/plain, */*",
                    "Referer": url_html,
                })
                # Hit the HTML page first to get Cloudflare clearance cookies
                session.get(url_html, timeout=30)
                # Hit the API endpoint using the cleared session
                resp = session.get(url_api, timeout=30)
                if resp.status_code == 200:
                    return resp.json().get("results", [])
                else:
                    logger.error(f"Bain API returned {resp.status_code}")
                    return []
                    
            results = await asyncio.to_thread(fetch_jobs)
            for job in results:
                title = job.get("JobTitle", "Unknown Role")
                link = job.get("Link", "")
                if link and link.startswith("/"):
                    link = urljoin("https://www.bain.com", link)
                job_id = job.get("JobId", "")
                locs = job.get("Location", [])
                location = ", ".join(locs) if locs else "Unknown"
                
                listings.append(JobListing(
                    role_name=title,
                    job_listing_link=link,
                    location=location,
                    jobid=job_id
                ))
        except Exception as e:
            logger.error(f"Error scraping Bain portal: {e}")
            
        return listings
