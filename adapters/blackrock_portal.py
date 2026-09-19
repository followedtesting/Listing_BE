import logging
import asyncio
import json
import urllib.request
import ssl
from typing import List
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class BlackRockPortalAdapter(BaseJobAdapter):
    @property
    def portal_name(self) -> str:
        return "BlackRock"
        
    @property
    def portal_id(self) -> str:
        return "blackrock"
        
    async def scrape(self) -> List[JobListing]:
        # Using the exact intercepted API URL for "Engineering" and "Technology" facets in India
        url = "https://careers.blackrock.com/search-jobs/results?ActiveFacetID=Technology&CurrentPage=1&RecordsPerPage=1000&TotalContentResults=&Distance=5&RadiusUnitType=0&Keywords=&Location=&ShowRadius=False&IsPagination=False&CustomFacetName=&FacetTerm=1269750&FacetType=2&FacetFilters%5B0%5D.ID=Engineering&FacetFilters%5B0%5D.FacetType=5&FacetFilters%5B0%5D.Count=29&FacetFilters%5B0%5D.Display=Engineering&FacetFilters%5B0%5D.IsApplied=true&FacetFilters%5B0%5D.FieldName=custom_fields.MainTeam&FacetFilters%5B1%5D.ID=Technology&FacetFilters%5B1%5D.FacetType=5&FacetFilters%5B1%5D.Count=4&FacetFilters%5B1%5D.Display=Technology&FacetFilters%5B1%5D.IsApplied=true&FacetFilters%5B1%5D.FieldName=custom_fields.MainTeam&FacetFilters%5B2%5D.ID=1269750&FacetFilters%5B2%5D.FacetType=2&FacetFilters%5B2%5D.Count=65&FacetFilters%5B2%5D.Display=India&FacetFilters%5B2%5D.IsApplied=true&FacetFilters%5B2%5D.FieldName=&SearchResultsModuleName=Section+3+-+Search+Results&SearchFiltersModuleName=Section+3+-+Search+Filters&SortCriteria=0&SortDirection=0&SearchType=3&OrganizationIds=45831&PostalCode=&ResultsType=1&fc=&fl=&fcf=&afc=&afl=&afcf=&TotalContentPages=NaN"
        
        listings = []
        try:
            def fetch_jobs():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                # Disable SSL verification since certifi on the local macOS env occasionally fails with urllib
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    html = data.get("results", "")
                    soup = BeautifulSoup(html, "html.parser")
                    jobs = soup.find_all("a", {"class": "section3__search-results-a"})
                    
                    extracted = []
                    for j in jobs:
                        title_tag = j.find(["h2", "h3"])
                        title = title_tag.get_text(strip=True) if title_tag else j.get_text(strip=True).split("\n")[0]
                        link = j.get("href")
                        if link and link.startswith("/"):
                            link = urljoin("https://careers.blackrock.com", link)
                            
                        loc_tag = j.find(class_="job-location")
                        location = loc_tag.get_text(strip=True) if loc_tag else "India"
                        
                        job_id = j.get("data-job-id", "")
                        
                        extracted.append(JobListing(
                            role_name=title,
                            job_listing_link=link,
                            location=location,
                            jobid=job_id
                        ))
                    return extracted

            listings = await asyncio.to_thread(fetch_jobs)
        except Exception as e:
            logger.error(f"Error scraping BlackRock portal: {e}")
            
        return listings
