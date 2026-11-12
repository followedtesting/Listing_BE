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


class ThreeMPortalAdapter(BaseJobAdapter):
    """
    Adapter for 3M Careers Portal (TalentBrew / Radancy platform).
    Target URL: https://careers.3m.com/en/search-jobs?k=&l=&orgIds=5
    Filters:
      - Country: "India" (FacetFilter ID: 1269750, FacetType: 2)
      - Category: "Engineering" (FacetFilter ID: 9444192, FacetType: 1)
                  OR "Information Technology" (FacetFilter ID: 9444352, FacetType: 1)
    Network Call:
      - GET https://careers.3m.com/en/search-jobs/results with query string serialized facets.
    """

    TARGET_URL = "https://careers.3m.com/en/search-jobs?k=&l=&orgIds=5"
    BASE_URL = "https://careers.3m.com"
    RESULTS_URL = "https://careers.3m.com/en/search-jobs/results"

    @property
    def portal_id(self) -> str:
        return "three_m_careers"

    @property
    def portal_name(self) -> str:
        return "3M Careers Portal"

    def _build_query_string(self, page: int = 1) -> str:
        """Constructs the exact TalentBrew serialized query string for facet filtering."""
        params = [
            ("ActiveFacetID", "9444352"),
            ("CurrentPage", str(page)),
            ("RecordsPerPage", "15"),
            ("TotalContentResults", ""),
            ("Distance", "50"),
            ("RadiusUnitType", "0"),
            ("Keywords", ""),
            ("Location", ""),
            ("ShowRadius", "False"),
            ("IsPagination", "False"),
            ("CustomFacetName", ""),
            ("FacetTerm", ""),
            ("FacetType", "0"),
            ("FacetFilters[0].ID", "9444192"),
            ("FacetFilters[0].FacetType", "1"),
            ("FacetFilters[0].Count", "25"),
            ("FacetFilters[0].Display", "Engineering"),
            ("FacetFilters[0].IsApplied", "true"),
            ("FacetFilters[0].FieldName", ""),
            ("FacetFilters[1].ID", "9444352"),
            ("FacetFilters[1].FacetType", "1"),
            ("FacetFilters[1].Count", "22"),
            ("FacetFilters[1].Display", "Information Technology"),
            ("FacetFilters[1].IsApplied", "true"),
            ("FacetFilters[1].FieldName", ""),
            ("FacetFilters[2].ID", "1269750"),
            ("FacetFilters[2].FacetType", "2"),
            ("FacetFilters[2].Count", "32"),
            ("FacetFilters[2].Display", "India"),
            ("FacetFilters[2].IsApplied", "true"),
            ("FacetFilters[2].FieldName", ""),
            ("SearchResultsModuleName", "Section 6 - Search Results List"),
            ("SearchFiltersModuleName", "Section 6 - Search Filters"),
            ("SortCriteria", "0"),
            ("SortDirection", "0"),
            ("SearchType", "5"),
            ("OrganizationIds", "5"),
            ("PostalCode", ""),
            ("ResultsType", "0"),
            ("fc", ""),
            ("fl", ""),
            ("fcf", ""),
            ("afc", ""),
            ("afl", ""),
            ("afcf", ""),
            ("TotalContentPages", "NaN"),
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

        job_links = soup.select("a.search-results-list__job-link, a[data-job-id]")
        for a in job_links:
            title = a.get_text(strip=True)
            tb_id = (a.get("data-job-id") or "").strip()
            href = (a.get("href") or "").strip()

            card = a.find_parent("li")
            req_el = card.select_one(".job-req-id, .requisition-id") if card else None
            req_id = req_el.get_text(strip=True) if req_el else ""

            job_id = req_id or tb_id
            if not job_id and href:
                job_id = href.rstrip("/").split("/")[-1]

            if not job_id or not title:
                continue

            if job_id in seen_ids:
                continue

            seen_ids.add(job_id)

            loc_el = card.select_one(".job-location, .location") if card else None
            loc_str = loc_el.get_text(strip=True) if loc_el else "India"
            if "india" not in loc_str.lower():
                loc_str = f"{loc_str}, India"

            full_link = f"{self.BASE_URL}{href}" if href.startswith("/") else href

            listings.append(
                JobListing(
                    jobid=job_id,
                    role_name=title,
                    job_listing_link=full_link,
                    location=loc_str,
                )
            )

        return listings, total_pages

    async def _scrape_curl(self) -> List[JobListing]:
        """Scrapes 3M careers using direct TalentBrew results endpoint via curl_cffi."""
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.TARGET_URL,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        page = 1

        async with AsyncSession(impersonate="chrome124") as session:
            while True:
                qs = self._build_query_string(page=page)
                url = f"{self.RESULTS_URL}?{qs}"

                resp = await session.get(url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    logger.warning(f"3M results API returned HTTP {resp.status_code} on page {page}")
                    break

                try:
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Failed to parse 3M JSON response on page {page}: {e}")
                    break

                results_html = data.get("results", "")
                if not results_html:
                    break

                page_listings, total_pages = self._parse_results_html(results_html, seen_ids)
                listings.extend(page_listings)

                if page >= total_pages or len(page_listings) == 0:
                    break
                page += 1

        logger.info(f"3M curl scraped {len(listings)} Engineering & IT jobs in India.")
        return listings

    async def _scrape_playwright(self) -> List[JobListing]:
        """Low-RAM Playwright fallback for 3M Careers."""
        logger.info("Attempting 3M scraping via Playwright fallback...")
        listings: List[JobListing] = []
        seen_ids: Set[str] = set()
        page = 1
        playwright_obj = None
        browser = None

        try:
            playwright_obj = await async_playwright().start()
            browser = await playwright_obj.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                    "--disable-extensions",
                    "--js-flags=--max-old-space-size=128",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            pw_page = await context.new_page()

            # Abort heavy static assets to conserve RAM
            await pw_page.route(
                "**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2,ttf,otf,eot,css,mp4,webm}",
                lambda route: route.abort(),
            )

            await pw_page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=40000)

            while True:
                qs = self._build_query_string(page=page)
                data = await pw_page.evaluate(
                    """
                    async (q) => {
                        try {
                            const res = await fetch("/en/search-jobs/results?" + q, {
                                headers: {
                                    "Accept": "application/json, text/javascript, */*; q=0.01",
                                    "X-Requested-With": "XMLHttpRequest"
                                }
                            });
                            return await res.json();
                        } catch (e) {
                            return { "error": e.message };
                        }
                    }
                    """,
                    qs,
                )

                if not isinstance(data, dict) or "error" in data:
                    logger.error(f"Error fetching 3M jobs in Playwright on page {page}: {data}")
                    break

                results_html = data.get("results", "")
                if not results_html:
                    break

                page_listings, total_pages = self._parse_results_html(results_html, seen_ids)
                listings.extend(page_listings)

                if page >= total_pages or len(page_listings) == 0:
                    break
                page += 1

            logger.info(f"3M Playwright scraped {len(listings)} jobs.")
        except Exception as e:
            logger.error(f"Playwright scraping error for 3M: {e}", exc_info=True)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_obj:
                try:
                    await playwright_obj.stop()
                except Exception:
                    pass
            gc.collect()

        return listings

    async def scrape(self) -> List[JobListing]:
        """Scrapes 3M Engineering and IT jobs in India with curl primary and Playwright fallback."""
        try:
            listings = await self._scrape_curl()
            if listings:
                return listings
            logger.warning("3M curl scraping returned 0 listings. Falling back to Playwright...")
        except Exception as e:
            logger.warning(f"3M curl scraping failed: {e}. Falling back to Playwright...")

        try:
            return await self._scrape_playwright()
        except Exception as e:
            logger.error(f"3M Playwright scraping failed: {e}")
            return []
