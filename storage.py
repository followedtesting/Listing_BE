import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from config import settings

logger = logging.getLogger(__name__)

class JSONJobStorage:
    @staticmethod
    def _get_file_path(portal_id: str) -> Path:
        return settings.data_path / f"last_listings_{portal_id}.json"

    @staticmethod
    def _get_new_listings_file_path(portal_id: str) -> Path:
        return settings.data_path / f"new_listings_{portal_id}.json"

    @classmethod
    def get_previous_listings(cls, portal_id: str) -> List[Dict[str, Any]]:
        file_path = cls._get_file_path(portal_id)
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading storage file for {portal_id}: {e}")
            return []

    @classmethod
    def get_new_listings(cls, portal_id: str) -> List[Dict[str, Any]]:
        file_path = cls._get_new_listings_file_path(portal_id)
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading new listings storage file for {portal_id}: {e}")
            return []

    @classmethod
    def save_listings(cls, portal_id: str, listings: List[Dict[str, Any]]) -> None:
        file_path = cls._get_file_path(portal_id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(listings, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(listings)} listings for portal '{portal_id}' to {file_path}")
        except Exception as e:
            logger.error(f"Error saving listings for {portal_id}: {e}")

    @classmethod
    def save_new_listings(cls, portal_id: str, listings: List[Dict[str, Any]]) -> None:
        file_path = cls._get_new_listings_file_path(portal_id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(listings, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(listings)} new listings for portal '{portal_id}' to {file_path}")
        except Exception as e:
            logger.error(f"Error saving new listings for {portal_id}: {e}")

    @classmethod
    def diff_and_update(cls, portal_id: str, current_listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Compares current listings with the previous run.
        Updates the stored file with current listings.
        Saves the detected diff (new listings) to a dedicated file.
        Returns a list of brand new listings.
        """
        file_path = cls._get_file_path(portal_id)
        
        # If no file exists, this is the first run.
        # We initialize the file, save empty list of new listings, and return empty.
        if not file_path.exists():
            logger.info(f"First run for portal '{portal_id}'. Initializing state with {len(current_listings)} listings.")
            cls.save_listings(portal_id, current_listings)
            cls.save_new_listings(portal_id, [])
            return []

        previous_listings = cls.get_previous_listings(portal_id)
        previous_ids = {str(item.get("jobid")) for item in previous_listings if item.get("jobid")}

        new_listings = []
        for item in current_listings:
            job_id = str(item.get("jobid"))
            if job_id and job_id not in previous_ids:
                new_listings.append(item)

        # Always update the stored state to current listings
        cls.save_listings(portal_id, current_listings)
        
        # Save the new listings diff
        cls.save_new_listings(portal_id, new_listings)
        
        return new_listings
