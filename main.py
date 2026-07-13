import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any

from config import settings
from storage import JSONJobStorage
from adapters.base import BaseJobAdapter
from adapters.microsoft_portal import MicrosoftPortalAdapter
from adapters.visa_portal import VisaPortalAdapter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# List of active adapters that will be scraped.
ACTIVE_ADAPTERS: List[BaseJobAdapter] = [
    MicrosoftPortalAdapter(),
    VisaPortalAdapter(),
]

app = FastAPI(
    title="Antigravity Job Listing Tracker",
    description="A FastAPI backend tracking job listings using Playwright.",
    version="1.0.0"
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
    """Helper task to run scraping and save diff in the background."""
    logger.info(f"--- Starting background scrape job for portal: {adapter.portal_name} ({adapter.portal_id}) ---")
    try:
        current_listings = await adapter.scrape()
        listings_data = [job.model_dump() for job in current_listings]
        new_listings = JSONJobStorage.diff_and_update(adapter.portal_id, listings_data)
        logger.info(f"Background scrape complete for '{adapter.portal_name}'. Found {len(new_listings)} new listings.")
    except Exception as e:
        logger.error(f"Error in background scrape task for '{adapter.portal_name}': {e}", exc_info=True)

@app.get("/")
def get_root():
    return {
        "app": "Antigravity Job Listing Tracker Backend",
        "status": "running",
        "data_dir": settings.DATA_DIR,
        "active_portals": [a.portal_id for a in ACTIVE_ADAPTERS]
    }

@app.get("/portals")
def get_portals():
    """Retrieves metadata of all active job portals including their stored listing counts."""
    return [
        {
            "id": a.portal_id,
            "name": a.portal_name,
            "current_listings_count": len(JSONJobStorage.get_previous_listings(a.portal_id)),
            "new_listings_count": len(JSONJobStorage.get_new_listings(a.portal_id))
        } for a in ACTIVE_ADAPTERS
    ]

@app.get("/listings/{portal_id}")
def get_stored_listings(portal_id: str):
    """Retrieves the last stored listings for a given portal."""
    adapter = next((a for a in ACTIVE_ADAPTERS if a.portal_id == portal_id), None)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Portal '{portal_id}' not found.")
    
    listings = JSONJobStorage.get_previous_listings(portal_id)
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
    
    listings = JSONJobStorage.get_new_listings(portal_id)
    return {
        "portal_id": portal_id,
        "portal_name": adapter.portal_name,
        "count": len(listings),
        "listings": listings
    }

@app.post("/trigger-scrape")
async def trigger_scrape_all(background_tasks: BackgroundTasks, background: bool = False):
    """
    Triggers scraping on all active portals.
    Can be run in the background (asynchronous) or foreground (returns results immediately).
    """
    if background:
        # Trigger background execution
        for adapter in ACTIVE_ADAPTERS:
            background_tasks.add_task(scrape_portal_task, adapter)
        return {"status": "triggered", "message": "Scraping jobs triggered in the background."}

    # Execute in the foreground to return current results
    results = {}
    for adapter in ACTIVE_ADAPTERS:
        try:
            current_listings = await adapter.scrape()
            listings_data = [job.model_dump() for job in current_listings]
            
            # Diff and save state
            new_listings = JSONJobStorage.diff_and_update(adapter.portal_id, listings_data)
            
            results[adapter.portal_id] = {
                "portal_name": adapter.portal_name,
                "total_scraped": len(listings_data),
                "new_listings_count": len(new_listings),
                "new_listings": new_listings
            }
        except Exception as e:
            logger.error(f"Error executing scrape for '{adapter.portal_name}': {e}", exc_info=True)
            results[adapter.portal_id] = {
                "portal_name": adapter.portal_name,
                "status": "error",
                "error": str(e)
            }
            
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
        new_listings = JSONJobStorage.diff_and_update(adapter.portal_id, listings_data)
        
        return {
            "status": "completed",
            "portal_name": adapter.portal_name,
            "total_scraped": len(listings_data),
            "new_listings_count": len(new_listings),
            "new_listings": new_listings
        }
    except Exception as e:
        logger.error(f"Error scraping single portal '{portal_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
