import logging
import json
from typing import List
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class GoldmanSachsPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "goldman_sachs_careers"

    @property
    def portal_name(self) -> str:
        return "Goldman Sachs Careers Portal"

    async def scrape(self) -> List[JobListing]:
        base_url = "https://higher.gs.com/results?EXPERIENCE_LEVEL=Analyst&LOCATION=Bengaluru|Hyderabad|Mumbai&page=1&search=software%20engineering&sort=RELEVANCE"
        logger.info(f"Navigating to Goldman Sachs Careers page to establish session context: {base_url}")
        
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
                
                await page.goto(base_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                
                page_number = 0
                pageSize = 20
                max_pages = 25  # Avoid runaway loops
                
                api_url = "https://api-higher.gs.com/gateway/api/v1/graphql"
                
                while page_number < max_pages:
                    logger.info(f"Fetching Goldman Sachs careers pageNumber {page_number}...")
                    
                    payload = {
                        "operationName": "GetRoles",
                        "variables": {
                            "searchQueryInput": {
                                "page": {
                                    "pageSize": pageSize,
                                    "pageNumber": page_number
                                },
                                "sort": {
                                    "sortStrategy": "RELEVANCE",
                                    "sortOrder": "DESC"
                                },
                                "filters": [
                                    {
                                        "filterCategoryType": "EXPERIENCE_LEVEL",
                                        "filters": [
                                            {
                                                "filter": "Analyst",
                                                "subFilters": []
                                            }
                                        ]
                                    },
                                    {
                                        "filterCategoryType": "LOCATION",
                                        "filters": [
                                            {
                                                "filter": "India",
                                                "subFilters": [
                                                    {
                                                        "filter": "Karnataka",
                                                        "subFilters": [
                                                            {
                                                                "filter": "Bengaluru",
                                                                "subFilters": []
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "filter": "Maharashtra",
                                                        "subFilters": [
                                                            {
                                                                "filter": "Mumbai",
                                                                "subFilters": []
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "filter": "Telangana",
                                                        "subFilters": [
                                                            {
                                                                "filter": "Hyderabad",
                                                                "subFilters": []
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ],
                                "experiences": [
                                    "EARLY_CAREER",
                                    "PROFESSIONAL"
                                ],
                                "searchTerm": "software engineering"
                            }
                        },
                        "query": "query GetRoles($searchQueryInput: RoleSearchQueryInput!) {\n  roleSearch(searchQueryInput: $searchQueryInput) {\n    totalCount\n    items {\n      roleId\n      corporateTitle\n      jobTitle\n      jobFunction\n      locations {\n        primary\n        state\n        country\n        city\n        __typename\n      }\n      status\n      division\n      skills\n      jobType {\n        code\n        description\n        __typename\n      }\n      externalSource {\n        sourceId\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n}"
                    }
                    
                    payload_json_str = json.dumps(payload)
                    
                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('{api_url}', {{
                                    method: 'POST',
                                    headers: {{ 'Content-Type': 'application/json' }},
                                    body: JSON.stringify({payload_json_str})
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)
                    
                    if "error" in result:
                        logger.error(f"Error fetching Goldman Sachs listings at page {page_number}: {result['error']}")
                        break
                        
                    data_obj = result.get("data", {})
                    if not data_obj:
                        logger.info(f"No data object returned from Goldman Sachs API at page {page_number}. Stopping pagination.")
                        break
                        
                    role_search = data_obj.get("roleSearch", {})
                    total_count = role_search.get("totalCount", 0)
                    items = role_search.get("items", [])
                    
                    if not items:
                        logger.info(f"No items returned in roleSearch at page {page_number}. Stopping pagination.")
                        break
                        
                    page_listings_count = 0
                    duplicate_found = False
                    
                    for item in items:
                        ext_source = item.get("externalSource", {})
                        source_id = ext_source.get("sourceId") if isinstance(ext_source, dict) else None
                        jobid = str(source_id or item.get("roleId", "")).strip()
                        title = item.get("jobTitle", "").strip()
                        
                        if jobid and title:
                            if jobid in seen_ids:
                                logger.info(f"Encountered duplicate jobid '{jobid}' at page {page_number}. Stopping pagination.")
                                duplicate_found = True
                                break
                                
                            seen_ids.add(jobid)
                            page_listings_count += 1
                            job_link = f"https://higher.gs.com/roles/{jobid}"
                            
                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title,
                                    job_listing_link=job_link
                                )
                            )
                            
                    logger.info(f"Scraped {page_listings_count} jobs from Goldman Sachs page {page_number}.")
                    
                    if duplicate_found or len(items) < pageSize or (total_count and len(seen_ids) >= total_count):
                        logger.info(f"Reached end of listings for Goldman Sachs (total scraped: {len(seen_ids)}, total available: {total_count}). Stopping pagination.")
                        break
                        
                    page_number += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape Goldman Sachs Careers Portal: {e}", exc_info=True)
                raise
            finally:
                await browser.close()
                
        logger.info(f"Finished Goldman Sachs Careers scrape. Found total {len(listings)} listings.")
        return listings
