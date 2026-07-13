from abc import ABC, abstractmethod
from typing import List
from pydantic import BaseModel, HttpUrl

class JobListing(BaseModel):
    jobid: str
    role_name: str
    job_listing_link: str

    class Config:
        # Allow extra fields if some portals return additional details
        extra = "allow"

class BaseJobAdapter(ABC):
    @property
    @abstractmethod
    def portal_id(self) -> str:
        """Unique slug identifier for the portal (used for file storage names, etc.)"""
        pass

    @property
    @abstractmethod
    def portal_name(self) -> str:
        """Human-readable name of the portal"""
        pass

    @abstractmethod
    async def scrape(self) -> List[JobListing]:
        """
        Runs playwright/scraping logic to fetch the latest job listings.
        Must return a list of JobListing objects.
        """
        pass
