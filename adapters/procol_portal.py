import logging
import asyncio
import json
import ssl
import urllib.request
import re
from typing import List, Set
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)

class ProcolPortalAdapter(BaseJobAdapter):
    @property
    def portal_id(self) -> str:
        return "procol_careers"

    @property
    def portal_name(self) -> str:
        return "Procol Careers Portal"

    def _extract_engineering_jobs(self, html: str) -> List[JobListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        # Method 1: DOM parsing from #open-positions section filtered by Engineering
        sec = soup.find(id="open-positions")
        if sec:
            for s in sec.find_all("section"):
                h3 = s.find(["h2", "h3", "h4", "h5", "h6"])
                if not h3:
                    continue
                dept_name = h3.get_text(" ", strip=True).lower()
                if "engineering" not in dept_name:
                    continue

                for a in s.find_all("a", href=True):
                    href = a["href"].strip()
                    full_url = href if href.startswith("http") else f"https://www.procol.ai{href}"
                    slug = href.strip("/").split("/")[-1]

                    # Extract role title
                    title_elem = a.find("span", class_=lambda c: c and "font-medium" in c and "text-black" in c)
                    title = title_elem.get_text(strip=True) if title_elem else a.get_text(" ", strip=True)
                    title = re.sub(r"\bView role\b.*$", "", title).strip()

                    # Extract location or default to Gurugram, India
                    card_text = a.get_text(" ", strip=True)
                    loc = "Gurugram, India"
                    for city in ["Gurugram", "Mumbai", "Bangalore", "Bengaluru", "Remote"]:
                        if city.lower() in card_text.lower():
                            loc = f"{city}, India" if city.lower() != "remote" else "Remote"
                            break

                    if slug and title and slug not in seen_ids:
                        seen_ids.add(slug)
                        listings.append(
                            JobListing(
                                jobid=slug,
                                role_name=title,
                                job_listing_link=full_url,
                                location=loc,
                            )
                        )

        # Method 2: Schema.org JSON-LD ItemList fallback
        if not listings:
            scripts = soup.find_all("script", type="application/ld+json")
            for sc in scripts:
                try:
                    content = sc.string or ""
                    if "ItemList" not in content or "Engineering" not in content:
                        continue
                    data = json.loads(content)
                    if isinstance(data, list):
                        data = data[0]
                    main_entity = data.get("mainEntity", {})
                    if main_entity.get("@type") == "ItemList":
                        for item in main_entity.get("itemListElement", []):
                            name_raw = item.get("name", "")
                            url = item.get("url", "")
                            if "(engineering)" in name_raw.lower():
                                role_name = re.sub(r"\s*\(engineering\)\s*", "", name_raw, flags=re.IGNORECASE).strip()
                                slug = url.strip("/").split("/")[-1]
                                if slug and slug not in seen_ids:
                                    seen_ids.add(slug)
                                    listings.append(
                                        JobListing(
                                            jobid=slug,
                                            role_name=role_name,
                                            job_listing_link=url,
                                            location="Gurugram, India",
                                        )
                                    )
                except Exception as ex:
                    logger.debug(f"JSON-LD parse error for Procol: {ex}")

        return listings

    async def _fetch_html_curl(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with AsyncSession(impersonate="chrome124", headers=headers) as s:
            resp = await s.get(url, timeout=25)
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"curl_cffi returned status {resp.status_code} for Procol")
            return ""

    async def _fetch_html_urllib(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        def fetch():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8")
            return ""

        try:
            return await asyncio.to_thread(fetch)
        except Exception as e:
            logger.error(f"urllib error for Procol: {e}")
            return ""

    async def scrape(self) -> List[JobListing]:
        url = "https://www.procol.ai/careers/"
        logger.info(f"Scraping Procol Careers (Engineering): {url}")

        html = ""
        try:
            html = await self._fetch_html_curl(url)
        except Exception as e:
            logger.warning(f"curl_cffi fetch failed for Procol: {e}")

        if not html:
            logger.info("Trying urllib fallback for Procol...")
            html = await self._fetch_html_urllib(url)

        if not html:
            logger.error("Failed to retrieve HTML for Procol Careers.")
            return []

        listings = self._extract_engineering_jobs(html)
        logger.info(f"Finished Procol Careers scrape. Found total {len(listings)} Engineering listings.")
        return listings
