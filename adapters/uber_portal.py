import logging
import asyncio
from typing import List
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

# Tech/Engineering/Product/Science categories and keywords
TECH_TEAMS = {"engineer", "product", "science", "design", "data", "it", "technology", "tech"}
TECH_KEYWORDS = [
    "engineer", "developer", "scientist", "product", "architect", "data", "tech", "qa",
    "sde", "software", "devops", "infrastructure", "security", "frontend", "backend",
    "fullstack", "mobile", "ios", "android", "ai", "ml"
]

class UberPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "uber_careers"

    @property
    def portal_name(self) -> str:
        return "Uber Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://jobs.uber.com/api/jobs/search/?countries=India"
        listings = []
        seen_ids = set()
        page = 1
        max_pages = 20
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://jobs.uber.com/en/jobs/",
        }

        try:
            async with AsyncSession(impersonate="chrome124") as s:
                while page <= max_pages:
                    url = f"{base_url}&page={page}"
                    logger.info(f"Fetching Uber jobs page {page}: {url}")
                    
                    response = await s.get(url, headers=headers, timeout=20)
                    if response.status_code != 200:
                        logger.warning(f"Uber API returned status code {response.status_code} on page {page}")
                        break

                    try:
                        data = response.json()
                    except Exception as je:
                        logger.error(f"Failed to parse JSON from Uber API on page {page}: {je}")
                        break

                    jobs = data.get("jobs", [])
                    if not jobs:
                        logger.info(f"No more jobs returned on page {page}.")
                        break

                    for j in jobs:
                        job_id = j.get("Id")
                        title = j.get("Title", "").strip()
                        
                        if not job_id or not title or job_id in seen_ids:
                            continue

                        # Check if job belongs to Tech/Engineering/Product/Science/Data
                        teams = [str(t).lower() for t in j.get("Teams", [])]
                        is_tech = any(t in TECH_TEAMS for t in teams)
                        if not is_tech:
                            title_lower = title.lower()
                            is_tech = any(kw in title_lower for kw in TECH_KEYWORDS)

                        if not is_tech:
                            continue

                        seen_ids.add(job_id)

                        location = "India"
                        locations = j.get("Locations", [])
                        if locations and isinstance(locations, list) and len(locations) > 0:
                            loc_data = locations[0]
                            city = loc_data.get("City", "").strip()
                            country = loc_data.get("Country", "").strip()
                            if city and country:
                                location = f"{city}, {country}"
                            elif city:
                                location = city
                            elif country:
                                location = country

                        job_link = ""
                        urls = j.get("Urls", [])
                        if urls and isinstance(urls, list) and len(urls) > 0:
                            rel_url = urls[0].get("Url", "")
                            if rel_url:
                                job_link = f"https://jobs.uber.com{rel_url}" if rel_url.startswith("/") else rel_url

                        if not job_link:
                            job_link = f"https://jobs.uber.com/en/jobs/{job_id}/"

                        listings.append(JobListing(
                            jobid=str(job_id),
                            role_name=title,
                            job_listing_link=job_link,
                            location=location
                        ))

                    total_pages = data.get("totalPages")
                    if total_pages is not None and page >= total_pages:
                        break

                    page += 1

                logger.info(f"Finished Uber Careers scrape. Found total {len(listings)} tech/engineering listings.")
        except Exception as e:
            logger.error(f"Error scraping Uber portal: {e}", exc_info=True)

        return listings

