import logging
import urllib.parse
from typing import List
from curl_cffi.requests import AsyncSession
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
        api_url = "https://www-api.ibm.com/search/api/v2"
        logger.info(f"Fetching IBM Careers listings via direct Search API: {api_url}")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }

        listings: List[JobListing] = []
        seen_ids = set()
        from_offset = 0
        size = 100
        max_pages = 50

        async with AsyncSession(impersonate="chrome120") as session:
            while from_offset < (max_pages * size):
                payload = {
                    "appId": "careers",
                    "scopes": ["careers2"],
                    "query": { "bool": { "must": [] } },
                    "post_filter": {
                        "bool": {
                            "must": [
                                { "term": { "field_keyword_08": "Software Engineering" } },
                                { "term": { "field_keyword_05": "India" } }
                            ]
                        }
                    },
                    "size": size,
                    "from": from_offset,
                    "sort": [
                        { "_score": "desc" },
                        { "pageviews": "desc" }
                    ],
                    "lang": "zz",
                    "_source": [
                        "_id",
                        "title",
                        "url"
                    ]
                }

                try:
                    resp = await session.post(api_url, json=payload, headers=headers, timeout=30)
                    if resp.status_code != 200:
                        logger.warning(f"IBM Search API returned non-200 status code {resp.status_code} at offset {from_offset}.")
                        break

                    data = resp.json()
                    hits_obj = data.get("hits", {})
                    total_hits = hits_obj.get("total", {}).get("value", 0)
                    hits_list = hits_obj.get("hits", [])

                    if not hits_list:
                        logger.info(f"No hits returned from IBM Search API at offset {from_offset}.")
                        break

                    new_on_page = 0
                    for h in hits_list:
                        source = h.get("_source", {})
                        title = (source.get("title") or "").strip()
                        url = (source.get("url") or "").strip()

                        if not title or not url:
                            continue

                        parsed_url = urllib.parse.urlparse(url)
                        qs = urllib.parse.parse_qs(parsed_url.query)
                        jobid = qs.get("jobId", [""])[0]

                        if not jobid:
                            jobid = str(source.get("_id") or h.get("_id"))

                        if jobid and jobid not in seen_ids:
                            seen_ids.add(jobid)
                            new_on_page += 1
                            listings.append(
                                JobListing(
                                    jobid=jobid,
                                    role_name=title,
                                    job_listing_link=url
                                )
                            )

                    logger.info(f"IBM API offset {from_offset}: Fetched {len(hits_list)} hits ({new_on_page} new). Total hits: {total_hits}")

                    if len(hits_list) < size or from_offset + len(hits_list) >= total_hits:
                        break

                    from_offset += size

                except Exception as page_err:
                    logger.error(f"Error fetching IBM API at offset {from_offset}: {page_err}", exc_info=True)
                    break

        logger.info(f"Finished IBM Careers scrape. Total {len(listings)} listings fetched.")
        return listings
