import gc
import json
import logging
from typing import List, Set
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class MaerskPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "maersk_careers"

    @property
    def portal_name(self) -> str:
        return "Maersk Careers Portal"

    def _get_payload(self, offset: int, limit: int) -> dict:
        return {
            "appliedFacets": {
                "locations": [
                    '4140682c689310014db3b323f82e0000', 'b726e4845aaf1000ae23f229f2170000',
                    'ac1e3f63dcb61001484cca8da0ee0000', '7b99c86bc5751001ee77c1dad0500000',
                    '7b88c76f001e10009e153d90f32d0000', '26c4d72049dc10009e1694dea72b0000',
                    'd8801e5af43d10009e1bfb079d6e0000', 'e78dddcb583810009e1b32f6dc380000',
                    'd8801e5af43d10009e1c6f60d76f0000', 'e78dddcb583810009e1299afb33f0000',
                    '7b88c76f001e10009e104f5ac5710000', '5fb6db3471ab10009e00c2b0912f0000',
                    'e78dddcb583810009dfef15511dd0000', '7b88c76f001e10009e1081ca16fc0000',
                    'd8801e5af43d10009e04f442bf430000', '9de49f588a0f10009e1c35c6900a0000',
                    'd8801e5af43d10009df3a49ebd480000', 'e27b2cd8aca310009e0d527ac7650000',
                    '7a38998ecd771001354b00da72100000', 'e78dddcb583810009e08889eadfe0000',
                    'ddba4775944910009e424afe3f850000', 'd8801e5af43d10009e0f6cca3a670000',
                    '5fb6db3471ab10009df11e5466840000', '26c4d72049dc10009e1c3d2fa2b50000',
                    'e27b2cd8aca310009e1a44220f6c0000', '5fb6db3471ab10009e0918d15dce0000',
                    'd8801e5af43d10009dfa3a8079340000', 'ddba4775944910009e1b192970560000',
                    '15350d48499210009e07c02b134d0000', '15350d48499210009e017164bb040000',
                    '853120f5cc8a10009e388f5d2aec0000', '15350d48499210009e1dac6cee0f0000',
                    '36d739e3210410014d09a17767590000', '260b68637fef1001e2bd40927d560000',
                    '9cbc082ae7f910013707c12d02c50000', '4e4d26638c45010787a37d5e5ad00000',
                    'c64e2feaec101001518738d6a9190000', '72baf0a31a0610014d090d9200e60000',
                    'f65203ee21d11001dc15d8486e340000', '4e4d26638c450107879f5562654c0000',
                    'fea35a9107ff10014ce73a337d340000', '4e4d26638c450107879f40e6fff00000',
                    '8df45049b43810013bfc511ded230000', '6fbaf2e5eafd1001035bccb694910000',
                    '4e4d26638c45010787a265e08d260000', '4e4d26638c45010787a25f43fa5f0000',
                    '4e4d26638c45010787a25b0edea60000', '0829310dd78f100197add0dc5cc90000',
                    '4e4d26638c45010787a4082f00a70000', '4e4d26638c45010787a25209b00e0000',
                    '4e4d26638c450107879f19c9b39b0000'
                ],
                "jobFamilyGroup": ["0d1a9a0723441001ef28e3fa8deb0000"]
            },
            "limit": limit,
            "offset": offset,
            "searchText": ""
        }

    def _parse_job_postings(self, job_postings: list, seen_ids: Set[str]) -> tuple[List[JobListing], bool]:
        listings = []
        duplicate_found = False
        for job in job_postings:
            title = (job.get("title") or "").strip()
            ext_path = (job.get("externalPath") or "").strip()
            bullet_fields = job.get("bulletFields") or []

            jobid = ""
            if bullet_fields and len(bullet_fields) > 0:
                jobid = str(bullet_fields[0]).strip()

            if not jobid:
                if "_" in ext_path:
                    jobid = ext_path.split("_")[-1]
                else:
                    jobid = ext_path.split("/")[-1]

            if not jobid or not title:
                continue

            if jobid in seen_ids:
                duplicate_found = True
                break

            seen_ids.add(jobid)

            if ext_path.startswith("http"):
                job_listing_link = ext_path
            else:
                job_listing_link = f"https://maersk.wd3.myworkdayjobs.com/Maersk_Careers{ext_path}"

            loc = job.get("locationsText") or "India"

            listings.append(
                JobListing(
                    jobid=jobid.strip(),
                    role_name=title.strip(),
                    job_listing_link=job_listing_link.strip(),
                    location=loc,
                )
            )
        return listings, duplicate_found

    async def _scrape_curl(self) -> List[JobListing]:
        api_url = "https://maersk.wd3.myworkdayjobs.com/wday/cxs/maersk/Maersk_Careers/jobs"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://maersk.wd3.myworkdayjobs.com/Maersk_Careers",
            "Origin": "https://maersk.wd3.myworkdayjobs.com"
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        offset = 0
        limit = 20
        max_safety_limit = 200

        async with AsyncSession(impersonate="chrome124") as s:
            while offset < max_safety_limit:
                payload = self._get_payload(offset, limit)
                resp = await s.post(api_url, json=payload, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"Maersk Workday API returned {resp.status_code} at offset {offset}")
                    break

                result = resp.json()
                job_postings = result.get("jobPostings", [])
                if not job_postings:
                    break

                new_listings, duplicate_found = self._parse_job_postings(job_postings, seen_ids)
                listings.extend(new_listings)

                if duplicate_found or len(job_postings) < limit:
                    break

                offset += limit

        logger.info(f"Maersk curl scraped {len(listings)} listings.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        logger.info("Falling back to Playwright (low-RAM) for Maersk...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                    "--disable-extensions",
                    "--js-flags=--max-old-space-size=128",
                ]
            )
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.route(
                    "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                    lambda route: route.abort()
                )
                await page.goto("https://maersk.wd3.myworkdayjobs.com/Maersk_Careers", wait_until="domcontentloaded", timeout=30000)

                offset = 0
                limit = 20
                max_safety_limit = 200

                while offset < max_safety_limit:
                    payload = self._get_payload(offset, limit)

                    result = await page.evaluate(f"""
                        async () => {{
                            try {{
                                const response = await fetch('/wday/cxs/maersk/Maersk_Careers/jobs', {{
                                    method: 'POST',
                                    headers: {{ 'Content-Type': 'application/json', 'Accept': 'application/json' }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                return await response.json();
                            }} catch (err) {{
                                return {{ "error": err.message }};
                            }}
                        }}
                    """)

                    if not result or "error" in result:
                        break

                    job_postings = result.get("jobPostings", [])
                    if not job_postings:
                        break

                    new_listings, duplicate_found = self._parse_job_postings(job_postings, seen_ids)
                    listings.extend(new_listings)

                    if duplicate_found or len(job_postings) < limit:
                        break

                    offset += limit
            finally:
                await browser.close()

        return listings

    async def scrape(self) -> List[JobListing]:
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
        except Exception as e:
            logger.warning(f"Maersk curl scraping error: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        finally:
            gc.collect()
