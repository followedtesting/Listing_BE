from contextlib import asynccontextmanager
import asyncio
import gc
import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from config import settings
from database import init_db
from storage import JobStorage, JSONJobStorage, QueueStorage
from sandbox import run_adapter_with_retries, cancel_active_sandbox, reset_sandbox_abort
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
from adapters.databricks_portal import DatabricksPortalAdapter
from adapters.paytm_portal import PaytmPortalAdapter
from adapters.amadeus_portal import AmadeusPortalAdapter
from adapters.phonepe_portal import PhonePePortalAdapter
from adapters.citi_portal import CitiPortalAdapter
from adapters.maersk_portal import MaerskPortalAdapter
from adapters.fractal_portal import FractalPortalAdapter
from adapters.cvent_portal import CventPortalAdapter
from adapters.cadence_portal import CadencePortalAdapter
from adapters.expedia_portal import ExpediaPortalAdapter
from adapters.wellsfargo_portal import WellsFargoPortalAdapter
from adapters.innovaccer_portal import InnovaccerPortalAdapter
from adapters.uhg_portal import UHGPortalAdapter
from adapters.nvidia_portal import NvidiaPortalAdapter
from adapters.amd_portal import AMDPortalAdapter
from adapters.bcg_portal import BCGPortalAdapter
from adapters.ibm_portal import IBMPortalAdapter
from adapters.morgan_stanley_portal import MorganStanleyPortalAdapter
from adapters.mckinsey_portal import McKinseyPortalAdapter
from adapters.sprinklr_portal import SprinklrPortalAdapter
from adapters.bank_of_america_portal import BankOfAmericaPortalAdapter
from adapters.tiger_analytics_portal import TigerAnalyticsPortalAdapter
from adapters.paypal_portal import PaypalPortalAdapter
from adapters.google_portal import GooglePortalAdapter
from adapters.bakerhughes_portal import BakerHughesPortalAdapter
from adapters.ericsson_portal import EricssonPortalAdapter
from adapters.siemens_portal import SiemensPortalAdapter
from adapters.ust_portal import USTPortalAdapter
from adapters.bain_portal import BainPortalAdapter
from adapters.pitney_bowes_portal import PitneyBowesPortalAdapter
from adapters.docusign_portal import DocuSignPortalAdapter
from adapters.rippling_portal import RipplingPortalAdapter
from adapters.stripe_portal import StripePortalAdapter
from adapters.micron_portal import MicronPortalAdapter
from adapters.bytedance_portal import ByteDancePortalAdapter
from adapters.grab_portal import GrabPortalAdapter
from adapters.shopee_portal import ShopeePortalAdapter
from adapters.agoda_portal import AgodaPortalAdapter
from adapters.revolut_portal import RevolutPortalAdapter
from adapters.okx_portal import OKXPortalAdapter
from adapters.okta_portal import OktaPortalAdapter
from adapters.telekom_portal import TelekomPortalAdapter
from adapters.paloalto_portal import PaloAltoPortalAdapter
from adapters.freshworks_portal import FreshworksPortalAdapter
from adapters.ukg_portal import UKGPortalAdapter
from adapters.shurutech_portal import ShuruTechPortalAdapter
from adapters.sprouts_portal import SproutsPortalAdapter
from adapters.blackrock_portal import BlackRockPortalAdapter
from adapters.mastercard_portal import MastercardPortalAdapter
from adapters.teradata_portal import TeradataPortalAdapter
from adapters.tenarai_portal import TenaraiPortalAdapter
from adapters.thoughtworks_portal import ThoughtWorksPortalAdapter
from adapters.uber_portal import UberPortalAdapter
from adapters.zoho_portal import ZohoPortalAdapter
from adapters.swiggy_portal import SwiggyPortalAdapter
from adapters.target_portal import TargetPortalAdapter
from adapters.metaforms_portal import MetaformsPortalAdapter
from adapters.cred_portal import CredPortalAdapter
from adapters.zepto_portal import ZeptoPortalAdapter
from adapters.glean_portal import GleanPortalAdapter
from adapters.browserstack_portal import BrowserStackPortalAdapter
from adapters.postman_portal import PostmanPortalAdapter
from adapters.thoughtspot_portal import ThoughtSpotPortalAdapter
from adapters.devrev_portal import DevRevPortalAdapter
from adapters.snowflake_portal import SnowflakePortalAdapter
from adapters.lenovo_portal import LenovoPortalAdapter
from adapters.scispace_portal import SciSpacePortalAdapter
from adapters.palantir_portal import PalantirPortalAdapter
from adapters.mistral_portal import MistralPortalAdapter
from adapters.kraken_portal import KrakenPortalAdapter
from adapters.newrelic_portal import NewRelicPortalAdapter
from adapters.soprasteria_portal import SopraSteriaPortalAdapter
from adapters.vanguard_portal import VanguardPortalAdapter
from adapters.nationwide_portal import NationwidePortalAdapter
from adapters.doordash_portal import DoorDashPortalAdapter
from mailer import generate_email_html, send_html_email, send_resend_email, send_digest_email_auto


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
    # Initialize queue records for all active portals
    QueueStorage.init_queue([{"portal_id": a.portal_id, "portal_name": a.portal_name} for a in ACTIVE_ADAPTERS])
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
    DatabricksPortalAdapter(),
    PaytmPortalAdapter(),
    AmadeusPortalAdapter(),
    PhonePePortalAdapter(),
    CitiPortalAdapter(),
    MaerskPortalAdapter(),
    FractalPortalAdapter(),
    CventPortalAdapter(),
    CadencePortalAdapter(),
    ExpediaPortalAdapter(),
    WellsFargoPortalAdapter(),
    InnovaccerPortalAdapter(),
    UHGPortalAdapter(),
    NvidiaPortalAdapter(),
    AMDPortalAdapter(),
    BCGPortalAdapter(),
    IBMPortalAdapter(),
    MorganStanleyPortalAdapter(),
    McKinseyPortalAdapter(),
    SprinklrPortalAdapter(),
    BankOfAmericaPortalAdapter(),
    TigerAnalyticsPortalAdapter(),
    PaypalPortalAdapter(),
    GooglePortalAdapter(),
    BakerHughesPortalAdapter(),
    EricssonPortalAdapter(),
    SiemensPortalAdapter(),
    USTPortalAdapter(),
    BainPortalAdapter(),
    PitneyBowesPortalAdapter(),
    DocuSignPortalAdapter(),
    RipplingPortalAdapter(),
    StripePortalAdapter(),
    MicronPortalAdapter(),
    ByteDancePortalAdapter(),
    GrabPortalAdapter(),
    ShopeePortalAdapter(),
    AgodaPortalAdapter(),
    RevolutPortalAdapter(),
    OKXPortalAdapter(),
    OktaPortalAdapter(),
    TelekomPortalAdapter(),
    PaloAltoPortalAdapter(),
    FreshworksPortalAdapter(),
    UKGPortalAdapter(),
    ShuruTechPortalAdapter(),
    SproutsPortalAdapter(),
    BlackRockPortalAdapter(),
    MastercardPortalAdapter(),
    TeradataPortalAdapter(),
    TenaraiPortalAdapter(),
    ThoughtWorksPortalAdapter(),
    UberPortalAdapter(),
    ZohoPortalAdapter(),
    SwiggyPortalAdapter(),
    TargetPortalAdapter(),
    MetaformsPortalAdapter(),
    CredPortalAdapter(),
    ZeptoPortalAdapter(),
    GleanPortalAdapter(),
    BrowserStackPortalAdapter(),
    PostmanPortalAdapter(),
    ThoughtSpotPortalAdapter(),
    DevRevPortalAdapter(),
    SnowflakePortalAdapter(),
    LenovoPortalAdapter(),
    SciSpacePortalAdapter(),
    PalantirPortalAdapter(),
    MistralPortalAdapter(),
    KrakenPortalAdapter(),
    NewRelicPortalAdapter(),
    SopraSteriaPortalAdapter(),
    VanguardPortalAdapter(),
    NationwidePortalAdapter(),
    DoorDashPortalAdapter(),
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


# =========================================================================
# NEW QUEUE RUNNER & SANDBOXED SUBPROCESS CONTROLLER
# =========================================================================

queue_runner_lock = asyncio.Lock()
is_queue_running = False
queue_cancel_requested = False

class QueueStartRequest(BaseModel):
    portal_ids: Optional[List[str]] = None
    send_email: bool = True

async def run_database_queue_worker(send_email: bool = True):
    """
    Background worker that sequentially executes adapters from the NeonDB/JSON queue.
    Each adapter runs inside a separate, monitored 350 MB subprocess.
    Never crashes the main FastAPI server; automatically retries failed adapters.
    Dispatches a single HTML digest email over HTTPS Port 443 upon completion.
    """
    global is_queue_running, queue_cancel_requested
    if queue_runner_lock.locked():
        logger.warning("Queue runner is already active. Ignoring duplicate execution request.")
        return

    async with queue_runner_lock:
        is_queue_running = True
        queue_cancel_requested = False
        reset_sandbox_abort()
        logger.info("=== Starting Sandboxed Database Queue Runner (350 MB RAM per Subprocess) ===")
        total_processed = 0
        total_new_listings = 0
        report_data = []

        try:
            while True:
                # Immediate check: Has the user requested a cancellation or reset?
                if queue_cancel_requested or not is_queue_running:
                    logger.info("Queue execution cancelled/reset by user. Exiting worker loop.")
                    break

                # Step 1: Fetch next pending adapter atomically from NeonDB / storage (ordered by order_index)
                item = QueueStorage.get_next_pending()
                if not item:
                    logger.info("No more pending adapters in queue. Sequential run complete.")
                    break

                portal_id = item["portal_id"]
                portal_name = item["portal_name"]
                logger.info(f"--> [Queue] Starting next item: {portal_name} ({portal_id})...")

                # Step 2: Mark Running
                QueueStorage.update_status(portal_id, status="running")

                # Check if new listing AND old listing were both zero earlier
                prev_listings = JobStorage.get_previous_listings(portal_id)
                prev_new_listings = JobStorage.get_new_listings(portal_id)
                was_both_zero_earlier = (len(prev_listings) == 0 and len(prev_new_listings) == 0)
                del prev_listings
                del prev_new_listings

                # Step 3: Execute in 350 MB Subprocess with retries
                success, listings, error_msg, attempts = await run_adapter_with_retries(
                    portal_id=portal_id,
                    max_memory_mb=settings.SUBPROCESS_MEMORY_LIMIT_MB,
                    timeout_secs=settings.SUBPROCESS_TIMEOUT_SECONDS,
                    max_retries=settings.MAX_ADAPTER_RETRIES
                )

                # Check if cancelled during subprocess execution
                if queue_cancel_requested or not is_queue_running or error_msg == "QUEUE_RESET_ABORT":
                    logger.info(f"Queue cancelled during '{portal_id}' execution. Setting status to idle and exiting.")
                    QueueStorage.update_status(portal_id, status="idle")
                    break

                if success:
                    # Diff and save state
                    new_listings = JobStorage.diff_and_update(portal_id, listings)
                    total_scraped = len(listings)
                    new_count = len(new_listings)
                    total_new_listings += new_count

                    QueueStorage.update_status(portal_id, status="success", scraped_count=total_scraped, retry_count=attempts)
                    JobStorage.save_run_status(portal_id, status="success", scraped_count=total_scraped)

                    report_items = listings if was_both_zero_earlier else new_listings
                    report_data.append({
                        "portal_id": portal_id,
                        "portal_name": portal_name,
                        "was_both_zero_earlier": was_both_zero_earlier,
                        "total_scraped": total_scraped,
                        "new_listings_count": new_count,
                        "report_items": report_items
                    })
                    logger.info(f"--> [Queue] {portal_name} SUCCEEDED. Scraped: {total_scraped}, New: {new_count}")
                else:
                    QueueStorage.update_status(portal_id, status="failed", error_message=error_msg, retry_count=attempts)
                    JobStorage.save_run_status(portal_id, status="failed", error_message=error_msg)
                    logger.error(f"--> [Queue] {portal_name} FAILED after {attempts} attempt(s): {error_msg}")

                total_processed += 1
                gc.collect()

                if queue_cancel_requested or not is_queue_running:
                    logger.info("Queue cancel detected between adapter runs. Exiting.")
                    break

                await asyncio.sleep(1.0)  # Safe breathing room between subprocesses

            # Step 5: After all pending adapters finish, send email digest if requested
            if send_email and report_data and not queue_cancel_requested and is_queue_running:
                logger.info("Generating and dispatching HTML Email Digest via HTTPS Port 443 (Resend/Auto)...")
                html_content = generate_email_html(report_data)
                subject = f"Job Tracker Digest - {total_new_listings} New Listing(s) Found"
                email_sent, email_msg = send_digest_email_auto(subject, html_content)
                logger.info(f"Post-queue email result: {email_sent} - {email_msg}")

        except Exception as e:
            logger.error(f"Unexpected error in run_database_queue_worker: {e}", exc_info=True)
        finally:
            is_queue_running = False
            gc.collect()

@app.post("/queue/start")
async def start_queue_run(
    payload: QueueStartRequest = QueueStartRequest(),
    background_tasks: BackgroundTasks = None
):
    """
    Resets selected or all adapters in the NeonDB queue table to 'pending'
    and starts the background sequential worker running each in an isolated 350 MB subprocess.
    """
    global is_queue_running, queue_cancel_requested
    
    # If a previous worker is currently winding down after a reset, wait briefly for lock release
    if queue_runner_lock.locked() and not is_queue_running:
        for _ in range(20):
            await asyncio.sleep(0.1)
            if not queue_runner_lock.locked():
                break

    if is_queue_running or queue_runner_lock.locked():
        return {
            "status": "already_running",
            "message": "A queue sequential run is already in progress.",
            "summary": QueueStorage.get_queue_summary()
        }

    queue_cancel_requested = False
    reset_sandbox_abort()

    reset_count = QueueStorage.reset_queue_to_pending(payload.portal_ids)
    
    # Launch worker in background
    if background_tasks:
        background_tasks.add_task(run_database_queue_worker, payload.send_email)
    else:
        asyncio.create_task(run_database_queue_worker(payload.send_email))

    return {
        "status": "started",
        "queued_adapters": reset_count,
        "message": f"Queued {reset_count} adapter(s) for background 350MB sandboxed execution."
    }

@app.get("/queue/status")
def get_queue_status():
    """Returns the live progress and status of the background sequential queue."""
    summary = QueueStorage.get_queue_summary()
    summary["is_running"] = is_queue_running
    return summary

@app.post("/queue/reset")
async def reset_queue():
    """Resets all queue items back to 'idle', instantly cancels active subprocess, and stops queue."""
    global is_queue_running, queue_cancel_requested
    is_queue_running = False
    queue_cancel_requested = True
    cancel_active_sandbox()  # Instantly terminate any running adapter subprocess tree
    count = QueueStorage.reset_all_to_idle()
    summary = QueueStorage.get_queue_summary()
    summary["is_running"] = False
    return {"status": "reset", "reset_count": count, "summary": summary}




