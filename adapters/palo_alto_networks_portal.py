import asyncio
import gc
import logging
import urllib.parse
from typing import List, Set, Dict, Any, Tuple
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

from adapters.base import BaseJobAdapter, JobListing

logger = logging.getLogger(__name__)


class PaloAltoNetworksPortalAdapter(BaseJobAdapter):
    """
    Adapter for Palo Alto Networks Careers Portal (TalentBrew / Radancy platform).
    Target URL: https://jobs.paloaltonetworks.com/en/search-jobs?k=&l=&orgIds=47263
    
    Filters:
      - Country: "India" (FacetFilter ID: 1269750, FacetType: 2)
      - Department: "Product Engineering" (FacetFilter ID: 9376336, FacetType: 1)
      
    Network Call:
      - Primary: GET https://jobs.paloaltonetworks.com/en/search-jobs/results with query string serialized facets.
      - Secondary Fallback: Headless Playwright browser automation
    """

    TARGET_URL = "https://jobs.paloaltonetworks.com/en/search-jobs?k=&l=&orgIds=47263"
    BASE_URL = "https://jobs.paloaltonetworks.com"
    RESULTS_URL = "https://jobs.paloaltonetworks.com/en/search-jobs/results"

    ORGANIZATION_ID = "47263"
    SEARCH_RESULTS_MODULE = "Section 29 - Search Results"
    SEARCH_FILTERS_MODULE = "Section 29 - Search Filters"

    # Facet configuration
    CATEGORY_FACET_ID = "9376336"  # "Product Engineering"
    CATEGORY_DISPLAY = "Product Engineering"
    COUNTRY_FACET_ID = "1269750"    # "India"
    COUNTRY_DISPLAY = "India"

    @property
    def portal_id(self) -> str:
        return "palo_alto_networks_careers"

    @property
    def portal_name(self) -> str:
        return "Palo Alto Networks Careers Portal"

    def _build_query_string(self, page: int = 1) -> str:
        """Constructs the exact TalentBrew serialized query string for facet filtering."""
        params = [
            ("ActiveFacetID", self.CATEGORY_FACET_ID),
            ("CurrentPage", str(page)),
            ("RecordsPerPage", "15"),
            ("TotalContentResults", ""),
            ("Distance", "50"),
            ("RadiusUnitType", "0"),
            ("Keywords", ""),
            ("Location", ""),
            ("ShowRadius", "False"),
            ("IsPagination", "False" if page == 1 else "True"),
            ("CustomFacetName", ""),
            ("FacetTerm", ""),
            ("FacetType", "0"),
            ("FacetFilters[0].ID", self.CATEGORY_FACET_ID),
            ("FacetFilters[0].FacetType", "1"),
            ("FacetFilters[0].Count", "349"),
            ("FacetFilters[0].Display", self.CATEGORY_DISPLAY),
            ("FacetFilters[0].IsApplied", "true"),
            ("FacetFilters[0].FieldName", ""),
            ("FacetFilters[1].ID", self.COUNTRY_FACET_ID),
            ("FacetFilters[1].FacetType", "2"),
            ("FacetFilters[1].Count", "109"),
            ("FacetFilters[1].Display", self.COUNTRY_DISPLAY),
            ("FacetFilters[1].IsApplied", "true"),
            ("FacetFilters[1].FieldName", ""),
            ("SearchResultsModuleName", self.SEARCH_RESULTS_MODULE),
            ("SearchFiltersModuleName", self.SEARCH_FILTERS_MODULE),
            ("SortCriteria", "0"),
            ("SortDirection", "0"),
            ("SearchType", "5"),
            ("OrganizationIds", self.ORGANIZATION_ID),
            ("PostalCode", ""),
            ("ResultsType", "0"),
            ("fc", ""),
            ("fl", ""),
            ("fcf", ""),
            ("afc", ""),
            ("afl", ""),
            ("afcf", ""),
        ]
        return urllib.parse.urlencode(params)

    def _parse_results_html(self, results_html: str, seen_ids: Set[str]) -> Tuple[List[JobListing], int]:
        """Parses TalentBrew search results HTML and extracts JobListing items along with total pages."""
        listings: List[JobListing] = []
        soup = BeautifulSoup(results_html, "html.parser")

        sr_section = soup.select_one("#search-results")
        total_pages = 1
        if sr_section and sr_section.get("data-total-pages"):
            try:
                total_pages = int(sr_section.get("data-total-pages"))
            except ValueError:
                total_pages = 1

        # Locate job items
        job_links = soup.select("li.section29__search-results-li a.section29__search-results-link, a[data-job-id]")
        for a in job_links:
            job_id = (a.get("data-job-id") or "").strip()
            href = (a.get("href") or "").strip()

            if not job_id and href:
                import re
                m = re.search(r"/(\d+)(?:[/?#]|$)", href)
                if m:
                    job_id = m.group(1)

            if not job_id or job_id in seen_ids:
                continue

            # Extract title
            title_el = a.select_one("h2, .section29__search-results-job-title, [class*='job-title']")
            title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)
            if not title:
                continue

            # Extract location
            loc_el = a.select_one(".section29__result-location, [class*='result-location'], [class*='location']")
            location = loc_el.get_text(strip=True) if loc_el else "India"

            seen_ids.add(job_id)

            full_link = f"{self.BASE_URL}{href}" if href.startswith("/") else href
            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location=location,
                )
            )

        return listings, total_pages

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes Palo Alto Networks job results using curl_cffi AsyncSession with pagination."""
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.TARGET_URL,
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        page = 1
        max_pages = 50

        async with AsyncSession(impersonate="chrome124") as session:
            while page <= max_pages:
                qs = self._build_query_string(page=page)
                url = f"{self.RESULTS_URL}?{qs}"

                try:
                    resp = await session.get(url, headers=headers, timeout=25)
                    if resp.status_code != 200:
                        logger.warning(f"Palo Alto Networks results API returned status {resp.status_code} on page {page}")
                        break

                    data = resp.json()
                    results_html = data.get("results", "")
                    if not results_html:
                        break

                    page_listings, total_pages = self._parse_results_html(results_html, seen_ids)
                    listings.extend(page_listings)
                    logger.info(
                        f"Palo Alto Networks page {page}/{total_pages}: "
                        f"scraped {len(page_listings)} jobs (total so far: {len(listings)})"
                    )

                    if page >= total_pages or not page_listings:
                        break

                    page += 1
                except Exception as e:
                    logger.error(f"Error fetching Palo Alto Networks page {page}: {e}")
                    break

        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Playwright fallback for Palo Alto Networks careers portal."""
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()

        browser = None
        context = None
        page = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--single-process",
                    ],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                # Block heavy assets to minimize memory footprint
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ["image", "media", "font", "stylesheet"]
                    else route.continue_(),
                )

                logger.info(f"Navigating to Palo Alto Networks portal: {self.TARGET_URL}")
                await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                # Trigger filter selections via JavaScript DOM events
                await page.evaluate("""() => {
                    const pe = document.querySelector('input[data-display="Product Engineering"], #category-filter-23');
                    const india = document.querySelector('input[data-display="India"], #country-filter-27');
                    if (pe) {
                        pe.checked = true;
                        pe.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    if (india) {
                        india.checked = true;
                        india.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""")

                await asyncio.sleep(4)

                # Extract jobs from rendered DOM
                content = await page.content()
                page_listings, _ = self._parse_results_html(content, seen_ids)
                listings.extend(page_listings)

        except Exception as e:
            logger.error(f"Playwright scraping failed for Palo Alto Networks: {e}")
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            gc.collect()

        return listings

    async def scrape(self) -> List[JobListing]:
        """Main entry point: attempts high-speed curl_cffi first, falls back to Playwright."""
        try:
            listings = await self._scrape_curl()
            if listings:
                logger.info(f"Palo Alto Networks portal scraped {len(listings)} jobs via curl_cffi")
                return listings
            logger.warning("Palo Alto Networks curl_cffi returned 0 jobs, falling back to Playwright")
        except Exception as e:
            logger.warning(f"Palo Alto Networks curl_cffi failed ({e}), falling back to Playwright")

        listings = await self._scrape_playwright()
        logger.info(f"Palo Alto Networks portal scraped {len(listings)} jobs via Playwright")
        return listings
