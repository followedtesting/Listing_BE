import json
import logging
import re
import urllib.parse
from typing import List
from curl_cffi.requests import AsyncSession
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class StripePortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "stripe_careers"

    @property
    def portal_name(self) -> str:
        return "Stripe Careers Portal"

    async def scrape(self) -> List[JobListing]:
        url = (
            "https://stripe.com/careers/search"
            "?teams=Data+%26+Data+Science"
            "&teams=Infrastructure+%26+Corporate+Tech"
            "&teams=Machine+Learning"
            "&locations=Asia+Pacific--India1"
        )
        logger.info(f"Fetching Stripe Careers page: {url}")

        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        target_teams = set(query_params.get("teams", []))
        target_locations = set(query_params.get("locations", []))

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html"
        }

        listings: List[JobListing] = []
        seen_ids = set()

        async with AsyncSession(impersonate="chrome120") as session:
            try:
                resp = await session.get(url, headers=headers, timeout=30)
                if resp.status_code != 200:
                    logger.error(f"Stripe page returned status code {resp.status_code}.")
                    return []

                html_content = resp.text
                m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_content, re.DOTALL)
                if not m:
                    logger.error("Could not find __NEXT_DATA__ tag on Stripe careers page.")
                    return []

                next_data = json.loads(m.group(1))
                job_index_data = next_data.get("props", {}).get("pageProps", {}).get("jobIndexData", {})
                filters = job_index_data.get("filters", {})
                raw_listings = job_index_data.get("listings", [])

                teams = filters.get("teams", [])
                locations = filters.get("locations", [])

                # Map team filter names to indices
                matching_team_indices = set()
                if target_teams:
                    for idx, t in enumerate(teams):
                        if t.get("name") in target_teams:
                            matching_team_indices.add(idx)

                # Map location filter names/countryCode to indices
                matching_loc_indices = set()
                for idx, l in enumerate(locations):
                    lname = l.get("name", "")
                    code = l.get("countryCode", "")
                    if any("india" in loc.lower() for loc in target_locations):
                        if "india" in lname.lower() or code == "IN":
                            matching_loc_indices.add(idx)
                    else:
                        if any(loc.lower() in lname.lower() for loc in target_locations):
                            matching_loc_indices.add(idx)

                logger.info(
                    f"Stripe Filter: Matched team indices {matching_team_indices}, "
                    f"location indices {matching_loc_indices} out of {len(raw_listings)} total postings."
                )

                for job in raw_listings:
                    job_teams = set(job.get("teamIndices", []))
                    job_locs = set(job.get("locationIndices", []))

                    team_match = not matching_team_indices or bool(job_teams & matching_team_indices)
                    loc_match = not matching_loc_indices or bool(job_locs & matching_loc_indices)

                    if not (team_match and loc_match):
                        continue

                    title = (job.get("title") or "").strip()
                    gh_id = str(job.get("greenhouseId") or "")
                    slug = (job.get("slug") or "").strip()

                    if not title or not (slug or gh_id):
                        continue

                    jobid = gh_id if gh_id else slug
                    if slug:
                        link = f"https://stripe.com/careers/jobs/{slug}"
                    else:
                        link = f"https://stripe.com/careers/jobs/{gh_id}"

                    if jobid and jobid not in seen_ids:
                        seen_ids.add(jobid)
                        listings.append(
                            JobListing(
                                jobid=jobid,
                                role_name=title,
                                job_listing_link=link
                            )
                        )

            except Exception as e:
                logger.error(f"Failed to scrape Stripe Careers Portal: {e}", exc_info=True)
                raise

        logger.info(f"Finished Stripe Careers scrape. Found total {len(listings)} listings.")
        return listings
