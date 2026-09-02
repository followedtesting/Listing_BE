from contextlib import asynccontextmanager
import asyncio
import gc
import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any

from config import settings
from database import init_db
from storage import JobStorage, JSONJobStorage
from adapters.base import BaseJobAdapter
from adapters.microsoft_portal import MicrosoftPortalAdapter
from adapters.visa_portal import VisaPortalAdapter
from adapters.salesforce_portal import SalesforcePortalAdapter
from adapters.adobe_portal import AdobePortalAdapter
from adapters.servicenow_portal import ServiceNowPortalAdapter
from adapters.standard_chartered_portal import StandardCharteredPortalAdapter
from adapters.apple_portal import ApplePortalAdapter
from adapters.akamai_portal import AkamaiPortalAdapter
from adapters.goldman_sachs_portal import GoldmanSachsPortalAdapter
from adapters.nielsen_portal import NielsenPortalAdapter
from adapters.cisco_portal import CiscoPortalAdapter
from adapters.barclays_portal import BarclaysPortalAdapter
from adapters.razorpay_portal import RazorpayPortalAdapter
from adapters.amazon_portal import AmazonPortalAdapter
from adapters.zscaler_portal import ZscalerPortalAdapter
from adapters.nielseniq_portal import NielsenIQPortalAdapter
from adapters.nutanix_portal import NutanixPortalAdapter
from adapters.meesho_portal import MeeshoPortalAdapter
from adapters.everpure_portal import EverpurePortalAdapter
from adapters.thomson_reuters_portal import ThomsonReutersPortalAdapter
from adapters.netapp_portal import NetAppPortalAdapter
from adapters.fnz_portal import FNZPortalAdapter
from adapters.atlassian_portal import AtlassianPortalAdapter
from adapters.jpmc_portal import JPMCPortalAdapter
from adapters.oracle_portal import OraclePortalAdapter
from adapters.amex_portal import AmexPortalAdapter
from adapters.intuit_portal import IntuitPortalAdapter
from adapters.lseg_portal import LSEGPortalAdapter
from adapters.opentext_portal import OpenTextPortalAdapter
from mailer import generate_email_html, send_html_email

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database on startup if DATABASE_URL is set
    init_db()
    yield

# List of active adapters that will be scraped.
ACTIVE_ADAPTERS: List[BaseJobAdapter] = [
    MicrosoftPortalAdapter(),
    VisaPortalAdapter(),
    SalesforcePortalAdapter(),
    AdobePortalAdapter(),
    ServiceNowPortalAdapter(),
    StandardCharteredPortalAdapter(),
    ApplePortalAdapter(),
    AkamaiPortalAdapter(),
    GoldmanSachsPortalAdapter(),
    NielsenPortalAdapter(),
    CiscoPortalAdapter(),
    BarclaysPortalAdapter(),
    RazorpayPortalAdapter(),
    AmazonPortalAdapter(),
    ZscalerPortalAdapter(),
    NielsenIQPortalAdapter(),
    NutanixPortalAdapter(),
    MeeshoPortalAdapter(),
    EverpurePortalAdapter(),
    ThomsonReutersPortalAdapter(),
    NetAppPortalAdapter(),
    FNZPortalAdapter(),
    AtlassianPortalAdapter(),
    JPMCPortalAdapter(),
    OraclePortalAdapter(),
    AmexPortalAdapter(),
    IntuitPortalAdapter(),
    LSEGPortalAdapter(),
    OpenTextPortalAdapter(),
]

app = FastAPI(
    title="Antigravity Job Listing Tracker",
    description="A FastAPI backend tracking job listings using Playwright and NeonDB.",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS to allow access from React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify the actual origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def scrape_portal_task(adapter: BaseJobAdapter) -> None:
    """Helper task to run scraping and save diff in the background for a single portal."""
    logger.info(f"--- Starting background scrape job for portal: {adapter.portal_name} ({adapter.portal_id}) ---")
    try:
        current_listings = await adapter.scrape()
        listings_data = [job.model_dump() for job in current_listings]
        del current_listings
        
        new_listings = JobStorage.diff_and_update(adapter.portal_id, listings_data)
        JobStorage.save_run_status(adapter.portal_id, status="success", scraped_count=len(listings_data))
        del listings_data
        del new_listings
        logger.info(f"Background scrape complete for '{adapter.portal_name}'.")
    except Exception as e:
        logger.error(f"Error in background scrape task for '{adapter.portal_name}': {e}", exc_info=True)
        JobStorage.save_run_status(adapter.portal_id, status="failed", error_message=str(e))
    finally:
        gc.collect()

async def run_all_adapters_sequentially_task() -> None:
    """Runs all active adapters strictly sequentially in the background to minimize RAM usage."""
    logger.info("=== Starting Background Sequential Execution for ALL Portals (RAM Optimized) ===")
    for adapter in ACTIVE_ADAPTERS:
        await scrape_portal_task(adapter)
        gc.collect()
        await asyncio.sleep(5)

@app.get("/")
def get_root():
    return {
        "app": "Antigravity Job Listing Tracker Backend",
        "status": "running",
        "storage_backend": "NeonDB (PostgreSQL)" if JobStorage.is_db_enabled() else "JSON Storage",
        "data_dir": settings.DATA_DIR,
        "active_portals": [a.portal_id for a in ACTIVE_ADAPTERS]
    }

@app.get("/portals")
def get_portals():
    """Retrieves metadata of all active job portals including their stored listing counts and last run status."""
    return JobStorage.get_all_portals_metadata(ACTIVE_ADAPTERS)

@app.get("/listings/{portal_id}")
def get_stored_listings(portal_id: str):
    """Retrieves the last stored listings for a given portal."""
    adapter = next((a for a in ACTIVE_ADAPTERS if a.portal_id == portal_id), None)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Portal '{portal_id}' not found.")
    
    listings = JobStorage.get_previous_listings(portal_id)
    return {
        "portal_id": portal_id,
        "portal_name": adapter.portal_name,
        "count": len(listings),
        "listings": listings
    }

@app.get("/new-listings/{portal_id}")
def get_new_listings(portal_id: str):
    """Retrieves the latest new listings diff for a given portal."""
    adapter = next((a for a in ACTIVE_ADAPTERS if a.portal_id == portal_id), None)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Portal '{portal_id}' not found.")
    
    listings = JobStorage.get_new_listings(portal_id)
    return {
        "portal_id": portal_id,
        "portal_name": adapter.portal_name,
        "count": len(listings),
        "listings": listings
    }

@app.post("/trigger-scrape")
async def trigger_scrape_all(background_tasks: BackgroundTasks, background: bool = False):
    """
    Triggers scraping on all active portals strictly sequentially.
    Runs one adapter at a time and cleans RAM after each portal to minimize memory usage.
    """
    if background:
        background_tasks.add_task(run_all_adapters_sequentially_task)
        return {"status": "triggered", "message": "Sequential scraping jobs triggered in the background."}

    logger.info("=== Starting Foreground Sequential Execution for ALL Portals (RAM Optimized) ===")
    results = {}
    for adapter in ACTIVE_ADAPTERS:
        logger.info(f"--> Sequential Execution: Scraping portal '{adapter.portal_name}' ({adapter.portal_id})...")
        try:
            current_listings = await adapter.scrape()
            listings_data = [job.model_dump() for job in current_listings]
            del current_listings
            
            # Diff and save state via JobStorage
            new_listings = JobStorage.diff_and_update(adapter.portal_id, listings_data)
            
            total_scraped = len(listings_data)
            new_count = len(new_listings)
            
            JobStorage.save_run_status(adapter.portal_id, status="success", scraped_count=total_scraped)
            
            del listings_data
            del new_listings
            
            results[adapter.portal_id] = {
                "portal_name": adapter.portal_name,
                "total_scraped": total_scraped,
                "new_listings_count": new_count
            }
            logger.info(f"Finished scraping '{adapter.portal_name}'. Total: {total_scraped}, New: {new_count}")
        except Exception as e:
            logger.error(f"Error executing scrape for '{adapter.portal_name}': {e}", exc_info=True)
            JobStorage.save_run_status(adapter.portal_id, status="failed", error_message=str(e))
            results[adapter.portal_id] = {
                "portal_name": adapter.portal_name,
                "status": "error",
                "error": str(e)
            }
        finally:
            gc.collect()
            
    return {
        "status": "completed",
        "results": results
    }

@app.post("/trigger-scrape/{portal_id}")
async def trigger_scrape_single(portal_id: str):
    """Triggers scraping for a single specified portal and returns results immediately."""
    adapter = next((a for a in ACTIVE_ADAPTERS if a.portal_id == portal_id), None)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Portal '{portal_id}' not found.")
        
    try:
        current_listings = await adapter.scrape()
        listings_data = [job.model_dump() for job in current_listings]
        del current_listings
        
        new_listings = JobStorage.diff_and_update(adapter.portal_id, listings_data)
        
        total_scraped = len(listings_data)
        new_count = len(new_listings)
        
        JobStorage.save_run_status(adapter.portal_id, status="success", scraped_count=total_scraped)
        
        del listings_data
        
        return {
            "status": "completed",
            "portal_name": adapter.portal_name,
            "total_scraped": total_scraped,
            "new_listings_count": new_count,
            "new_listings": new_listings
        }
    except Exception as e:
        logger.error(f"Error scraping single portal '{portal_id}': {e}", exc_info=True)
        JobStorage.save_run_status(adapter.portal_id, status="failed", error_message=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        gc.collect()

@app.post("/trigger-scrape-sequential")
async def trigger_scrape_sequential():
    """
    Triggers all active adapters ONE BY ONE strictly sequentially with RAM cleanup.
    Checks if new listing AND old listing were both zero earlier for each portal.
    Collects report items, generates a formatted HTML email report, and sends it.
    """
    logger.info("=== Starting Sequential Adapter Execution for ALL Portals (RAM Optimized) ===")
    results = {}
    report_data = []
    total_new_listings = 0
    total_portals_scraped = 0

    for adapter in ACTIVE_ADAPTERS:
        logger.info(f"--> Sequential Run: Scraping portal '{adapter.portal_name}' ({adapter.portal_id})...")
        try:
            # Check baseline before scrape using unified JobStorage
            prev_listings = JobStorage.get_previous_listings(adapter.portal_id)
            prev_new_listings = JobStorage.get_new_listings(adapter.portal_id)
            was_both_zero_earlier = (len(prev_listings) == 0 and len(prev_new_listings) == 0)
            del prev_listings
            del prev_new_listings

            current_listings = await adapter.scrape()
            listings_data = [job.model_dump() for job in current_listings]
            del current_listings
            
            # Diff and save state
            new_listings = JobStorage.diff_and_update(adapter.portal_id, listings_data)
            
            total_scraped = len(listings_data)
            new_count = len(new_listings)
            
            JobStorage.save_run_status(adapter.portal_id, status="success", scraped_count=total_scraped)

            # Determine items for email digest:
            # Only new listings, OR all current listings if both new and old were zero earlier
            if was_both_zero_earlier:
                report_items = listings_data
            else:
                report_items = new_listings

            report_entry = {
                "portal_id": adapter.portal_id,
                "portal_name": adapter.portal_name,
                "was_both_zero_earlier": was_both_zero_earlier,
                "total_scraped": total_scraped,
                "new_listings_count": new_count,
                "report_items": report_items
            }
            
            results[adapter.portal_id] = {
                "portal_name": adapter.portal_name,
                "total_scraped": total_scraped,
                "new_listings_count": new_count
            }
            report_data.append(report_entry)
            total_new_listings += new_count
            total_portals_scraped += 1
            
            logger.info(f"Finished sequential scrape for '{adapter.portal_name}'. Total: {total_scraped}, New: {new_count}, Both zero earlier: {was_both_zero_earlier}")
        except Exception as e:
            logger.error(f"Error during sequential scrape for '{adapter.portal_name}': {e}", exc_info=True)
            JobStorage.save_run_status(adapter.portal_id, status="failed", error_message=str(e))
            report_entry = {
                "portal_id": adapter.portal_id,
                "portal_name": adapter.portal_name,
                "status": "error",
                "error": str(e),
                "report_items": []
            }
            results[adapter.portal_id] = report_entry
            report_data.append(report_entry)
        finally:
            gc.collect()

    # Build and send HTML Email Report
    logger.info("Generating HTML Email Digest...")
    html_content = generate_email_html(report_data)
    del report_data
    gc.collect()

    email_sent, email_msg = send_html_email(
        subject=f"Job Tracker Digest - {total_new_listings} New Listing(s) Found",
        html_content=html_content
    )
    del html_content
    gc.collect()

    return {
        "status": "completed",
        "total_portals_scraped": total_portals_scraped,
        "total_new_listings": total_new_listings,
        "email_sent": email_sent,
        "email_message": email_msg,
        "results": results
    }

@app.post("/send-digest-email")
async def send_digest_email():
    """
    Generates and sends an HTML email digest based on currently stored portal states in JobStorage.
    Can be called after individual portal scrapes complete (e.g. from frontend or cron).
    """
    logger.info("=== Generating and Sending HTML Email Digest from Storage ===")
    report_data = []
    total_new_listings = 0
    total_portals_scraped = 0

    for adapter in ACTIVE_ADAPTERS:
        try:
            prev_listings = JobStorage.get_previous_listings(adapter.portal_id)
            prev_new_listings = JobStorage.get_new_listings(adapter.portal_id)
            
            total_scraped = len(prev_listings)
            new_count = len(prev_new_listings)
            
            if prev_new_listings:
                report_items = prev_new_listings
                was_both_zero = False
            else:
                report_items = prev_listings
                was_both_zero = True if total_scraped > 0 else False

            report_entry = {
                "portal_id": adapter.portal_id,
                "portal_name": adapter.portal_name,
                "was_both_zero_earlier": was_both_zero,
                "total_scraped": total_scraped,
                "new_listings_count": new_count,
                "report_items": report_items
            }
            report_data.append(report_entry)
            total_new_listings += new_count
            total_portals_scraped += 1
        except Exception as e:
            logger.error(f"Error compiling email report for portal '{adapter.portal_name}': {e}", exc_info=True)

    logger.info("Generating HTML Email Digest...")
    html_content = generate_email_html(report_data)
    del report_data
    gc.collect()

    email_sent, email_msg = send_html_email(
        subject=f"Job Tracker Digest - {total_new_listings} New Listing(s) Found",
        html_content=html_content
    )
    del html_content
    gc.collect()

    return {
        "status": "completed",
        "total_portals": total_portals_scraped,
        "total_new_listings": total_new_listings,
        "email_sent": email_sent,
        "email_message": email_msg
    }



