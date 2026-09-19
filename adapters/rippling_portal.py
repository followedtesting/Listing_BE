import logging
from typing import List
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class RipplingPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "rippling_careers"

    @property
    def portal_name(self) -> str:
        return "Rippling Careers Portal"

    async def scrape(self) -> List[JobListing]:
        algolia_url = (
            "https://6fnax3tbef-dsn.algolia.net/1/indexes/*/queries"
            "?x-algolia-agent=Algolia%20for%20JavaScript&x-algolia-api-key=416caa4690f002ff6fe4a2097623640b&x-algolia-application-id=6FNAX3TBEF"
        )
        logger.info(f"Fetching Rippling Careers listings via Algolia REST API...")

        listings: List[JobListing] = []
        seen_ids = set()
        page = 0
        hits_per_page = 100
        max_pages = 20

        async with AsyncSession(impersonate="chrome120") as session:
            while page < max_pages:
                payload = {
                    "requests": [
                        {
                            "indexName": "careers_en-US_production",
                            "facetFilters": [
                                ["departmentName:Engineering"],
                                ["locationNames:Bangalore, India"]
                            ],
                            "hitsPerPage": hits_per_page,
                            "page": page,
                            "query": ""
                        }
                    ]
                }

                try:
                    resp = await session.post(algolia_url, json=payload, timeout=30)
                    if resp.status_code != 200:
                        logger.warning(f"Rippling Algolia API returned status {resp.status_code} on page {page}.")
                        break

                    data = resp.json()
                    results = data.get("results", [])
                    if not results:
                        break

                    res0 = results[0]
                    hits = res0.get("hits", [])
                    total_hits = res0.get("nbHits", 0)

                    logger.info(f"Rippling Algolia Page {page}: Fetched {len(hits)} hits (total nbHits: {total_hits}).")

                    if not hits:
                        break

                    new_on_page = 0
                    for hit in hits:
                        title = (hit.get("name") or hit.get("title") or "").strip()
                        jobid = str(hit.get("jobId") or hit.get("objectID") or "").strip()
                        url = hit.get("url") or f"https://ats.rippling.com/rippling/jobs/{jobid}"

                        if jobid and jobid not in seen_ids and title:
                            seen_ids.add(jobid)
                            new_on_page += 1
                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title,
                                    job_listing_link=url
                                )
                            )

                    if len(hits) < hits_per_page or (page + 1) * hits_per_page >= total_hits:
                        break

                    page += 1

                except Exception as page_err:
                    logger.error(f"Error fetching Rippling Algolia API page {page}: {page_err}", exc_info=True)
                    break

        logger.info(f"Finished Rippling Careers scrape. Total {len(listings)} listings fetched.")
        return listings
