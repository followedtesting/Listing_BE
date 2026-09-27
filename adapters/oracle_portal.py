import logging
from typing import List
from curl_cffi import requests
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class OraclePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "oracle_careers"

    @property
    def portal_name(self) -> str:
        return "Oracle Careers (HCM Cloud)"

    async def scrape(self) -> List[JobListing]:
        logger.info("Scraping Oracle Cloud Careers Portal.")

        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

        listings: List[JobListing] = []
        seen_ids = set()
        offset = 0
        limit = 25

        async with requests.AsyncSession(impersonate="chrome124", headers=headers) as session:
            while True:
                api_url = (
                    f"https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                    f"?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations"
                    f"&finder=findReqs;siteNumber=CX_45001,limit={limit},offset={offset},locationId=300000000106947,sortBy=POSTING_DATES_DESC"
                )

                try:
                    res = await session.get(api_url, timeout=15)
                    if res.status_code != 200:
                        logger.warning(f"Oracle HCM API returned status code {res.status_code} at offset {offset}")
                        break

                    data = res.json()
                    items = data.get("items", [])
                    if not items:
                        break

                    req_container = items[0]
                    total_jobs = req_container.get("TotalJobsCount", 0)
                    postings = req_container.get("requisitionList", [])

                    if not postings:
                        break

                    for job in postings:
                        job_id = str(job.get("Id") or job.get("RequisitionId") or "").strip()
                        title = (job.get("Title") or "").strip()

                        if job_id and title and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            full_link = f"https://careers.oracle.com/en/sites/jobsearch/job/{job_id}"
                            listings.append(
                                JobListing(
                                    jobid=job_id,
                                    role_name=title,
                                    job_listing_link=full_link
                                )
                            )

                    if len(postings) < limit or offset + len(postings) >= total_jobs:
                        break

                    offset += limit
                except Exception as e:
                    logger.error(f"Oracle HCM API scrape failed at offset {offset}: {e}")
                    break

        logger.info(f"Finished Oracle Careers scrape. Found total {len(listings)} listings.")
        return listings
