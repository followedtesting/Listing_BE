import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from config import settings
from database import get_db_session, get_database_url, JobListingModel, NewJobListingModel, AdapterRunModel

logger = logging.getLogger(__name__)

class FileJSONJobStorage:
    """Fallback file-based JSON storage implementation."""
    @staticmethod
    def _get_file_path(portal_id: str) -> Path:
        return settings.data_path / f"last_listings_{portal_id}.json"

    @staticmethod
    def _get_new_listings_file_path(portal_id: str) -> Path:
        return settings.data_path / f"new_listings_{portal_id}.json"

    @staticmethod
    def _get_run_status_file_path(portal_id: str) -> Path:
        return settings.data_path / f"run_status_{portal_id}.json"

    @classmethod
    def get_previous_listings(cls, portal_id: str) -> List[Dict[str, Any]]:
        file_path = cls._get_file_path(portal_id)
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading JSON storage for {portal_id}: {e}")
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
            logger.error(f"Error reading new listings JSON storage for {portal_id}: {e}")
            return []

    @classmethod
    def get_run_status(cls, portal_id: str) -> Optional[Dict[str, Any]]:
        file_path = cls._get_run_status_file_path(portal_id)
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading run status JSON for {portal_id}: {e}")
            return None

    @classmethod
    def save_run_status(cls, portal_id: str, status: str, error_message: Optional[str] = None, scraped_count: int = 0) -> None:
        file_path = cls._get_run_status_file_path(portal_id)
        data = {
            "portal_id": portal_id,
            "last_run_at": datetime.utcnow().isoformat(),
            "status": status,
            "error_message": error_message,
            "last_scraped_count": scraped_count
        }
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved run status for portal '{portal_id}' ({status}) to {file_path}")
        except Exception as e:
            logger.error(f"Error saving run status for {portal_id}: {e}")

    @classmethod
    def get_all_portals_metadata(cls, adapters: List[Any]) -> List[Dict[str, Any]]:
        res = []
        for a in adapters:
            run_info = cls.get_run_status(a.portal_id) or {}
            res.append({
                "id": a.portal_id,
                "name": a.portal_name,
                "current_listings_count": len(cls.get_previous_listings(a.portal_id)),
                "new_listings_count": len(cls.get_new_listings(a.portal_id)),
                "last_run_at": run_info.get("last_run_at"),
                "last_status": run_info.get("status"),
                "error_message": run_info.get("error_message")
            })
        return res

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
        file_path = cls._get_file_path(portal_id)
        if not file_path.exists():
            logger.info(f"First JSON run for portal '{portal_id}'. Initializing state with {len(current_listings)} listings.")
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

        cls.save_listings(portal_id, current_listings)
        cls.save_new_listings(portal_id, new_listings)
        return new_listings


class DBJobStorage:
    """NeonDB PostgreSQL storage implementation using SQLAlchemy."""
    
    @classmethod
    def get_all_portals_metadata(cls, adapters: List[Any]) -> List[Dict[str, Any]]:
        session = get_db_session()
        if not session:
            return FileJSONJobStorage.get_all_portals_metadata(adapters)
        try:
            from sqlalchemy import func
            current_counts = dict(
                session.query(JobListingModel.portal_id, func.count(JobListingModel.id))
                .group_by(JobListingModel.portal_id)
                .all()
            )
            new_counts = dict(
                session.query(NewJobListingModel.portal_id, func.count(NewJobListingModel.id))
                .group_by(NewJobListingModel.portal_id)
                .all()
            )
            runs = {
                r.portal_id: {
                    "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
                    "status": r.status,
                    "error_message": r.error_message,
                    "last_scraped_count": r.last_scraped_count
                }
                for r in session.query(AdapterRunModel).all()
            }

            res = []
            for a in adapters:
                pid = a.portal_id
                run_info = runs.get(pid) or FileJSONJobStorage.get_run_status(pid) or {}
                c_count = current_counts.get(pid)
                if c_count is None:
                    c_count = len(FileJSONJobStorage.get_previous_listings(pid))
                n_count = new_counts.get(pid)
                if n_count is None:
                    n_count = len(FileJSONJobStorage.get_new_listings(pid))

                res.append({
                    "id": pid,
                    "name": a.portal_name,
                    "current_listings_count": c_count,
                    "new_listings_count": n_count,
                    "last_run_at": run_info.get("last_run_at"),
                    "last_status": run_info.get("status"),
                    "error_message": run_info.get("error_message")
                })
            return res
        except Exception as e:
            logger.error(f"Error fetching batch portals metadata from DB: {e}")
            return FileJSONJobStorage.get_all_portals_metadata(adapters)
        finally:
            session.close()

    @classmethod
    def get_previous_listings(cls, portal_id: str) -> List[Dict[str, Any]]:
        session = get_db_session()
        if not session:
            return FileJSONJobStorage.get_previous_listings(portal_id)
        try:
            records = session.query(JobListingModel).filter(JobListingModel.portal_id == portal_id).all()
            return [
                {
                    "jobid": r.jobid,
                    "role_name": r.role_name,
                    "job_listing_link": r.job_listing_link
                }
                for r in records
            ]
        except Exception as e:
            logger.error(f"Error fetching previous listings from DB for {portal_id}: {e}")
            return []
        finally:
            session.close()

    @classmethod
    def get_new_listings(cls, portal_id: str) -> List[Dict[str, Any]]:
        session = get_db_session()
        if not session:
            return FileJSONJobStorage.get_new_listings(portal_id)
        try:
            records = session.query(NewJobListingModel).filter(NewJobListingModel.portal_id == portal_id).all()
            return [
                {
                    "jobid": r.jobid,
                    "role_name": r.role_name,
                    "job_listing_link": r.job_listing_link
                }
                for r in records
            ]
        except Exception as e:
            logger.error(f"Error fetching new listings from DB for {portal_id}: {e}")
            return []
        finally:
            session.close()

    @classmethod
    def get_run_status(cls, portal_id: str) -> Optional[Dict[str, Any]]:
        session = get_db_session()
        if not session:
            return FileJSONJobStorage.get_run_status(portal_id)
        try:
            run = session.query(AdapterRunModel).filter(AdapterRunModel.portal_id == portal_id).first()
            if not run:
                return FileJSONJobStorage.get_run_status(portal_id)
            return {
                "portal_id": run.portal_id,
                "last_run_at": run.last_run_at.isoformat() if run.last_run_at else None,
                "status": run.status,
                "error_message": run.error_message,
                "last_scraped_count": run.last_scraped_count
            }
        except Exception as e:
            logger.error(f"Error fetching run status from DB for {portal_id}: {e}")
            return FileJSONJobStorage.get_run_status(portal_id)
        finally:
            session.close()

    @classmethod
    def save_run_status(cls, portal_id: str, status: str, error_message: Optional[str] = None, scraped_count: int = 0) -> None:
        session = get_db_session()
        if not session:
            FileJSONJobStorage.save_run_status(portal_id, status, error_message, scraped_count)
            return
        try:
            run = session.query(AdapterRunModel).filter(AdapterRunModel.portal_id == portal_id).first()
            now = datetime.utcnow()
            if run:
                run.last_run_at = now
                run.status = status
                run.error_message = error_message
                run.last_scraped_count = scraped_count
            else:
                run = AdapterRunModel(
                    portal_id=portal_id,
                    last_run_at=now,
                    status=status,
                    error_message=error_message,
                    last_scraped_count=scraped_count
                )
                session.add(run)
            session.commit()
            logger.info(f"Saved run status to DB for portal '{portal_id}' ({status})")
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving run status to DB for {portal_id}: {e}")
        finally:
            session.close()

    @classmethod
    def save_listings(cls, portal_id: str, listings: List[Dict[str, Any]]) -> None:
        session = get_db_session()
        if not session:
            FileJSONJobStorage.save_listings(portal_id, listings)
            return
        try:
            # Clear previous active listings for this portal
            session.query(JobListingModel).filter(JobListingModel.portal_id == portal_id).delete()
            
            # Bulk insert current listings
            db_objects = [
                JobListingModel(
                    portal_id=portal_id,
                    jobid=str(item.get("jobid", "")),
                    role_name=str(item.get("role_name", "")),
                    job_listing_link=str(item.get("job_listing_link", ""))
                )
                for item in listings
                if item.get("jobid")
            ]
            session.bulk_save_objects(db_objects)
            session.commit()
            logger.info(f"Saved {len(db_objects)} listings to NeonDB for portal '{portal_id}'")
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving listings to DB for {portal_id}: {e}")
        finally:
            session.close()

    @classmethod
    def save_new_listings(cls, portal_id: str, listings: List[Dict[str, Any]]) -> None:
        session = get_db_session()
        if not session:
            FileJSONJobStorage.save_new_listings(portal_id, listings)
            return
        try:
            # Clear previous new diff listings for this portal
            session.query(NewJobListingModel).filter(NewJobListingModel.portal_id == portal_id).delete()
            
            # Bulk insert new listings diff
            db_objects = [
                NewJobListingModel(
                    portal_id=portal_id,
                    jobid=str(item.get("jobid", "")),
                    role_name=str(item.get("role_name", "")),
                    job_listing_link=str(item.get("job_listing_link", ""))
                )
                for item in listings
                if item.get("jobid")
            ]
            session.bulk_save_objects(db_objects)
            session.commit()
            logger.info(f"Saved {len(db_objects)} new listings diff to NeonDB for portal '{portal_id}'")
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving new listings to DB for {portal_id}: {e}")
        finally:
            session.close()

    @classmethod
    def seed_from_json_if_needed(cls, portal_id: str) -> None:
        """Seed NeonDB table from local JSON storage if DB is currently empty for portal."""
        session = get_db_session()
        if not session:
            return
        try:
            count = session.query(JobListingModel).filter(JobListingModel.portal_id == portal_id).count()
            if count == 0:
                json_listings = FileJSONJobStorage.get_previous_listings(portal_id)
                json_new = FileJSONJobStorage.get_new_listings(portal_id)
                if json_listings:
                    logger.info(f"Seeding NeonDB from existing JSON file for portal '{portal_id}' ({len(json_listings)} listings)...")
                    cls.save_listings(portal_id, json_listings)
                    cls.save_new_listings(portal_id, json_new)
        except Exception as e:
            logger.error(f"Error seeding NeonDB from JSON for {portal_id}: {e}")
        finally:
            session.close()

    @classmethod
    def diff_and_update(cls, portal_id: str, current_listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cls.seed_from_json_if_needed(portal_id)
        
        session = get_db_session()
        if not session:
            return FileJSONJobStorage.diff_and_update(portal_id, current_listings)
            
        try:
            previous_listings = cls.get_previous_listings(portal_id)
            if not previous_listings:
                logger.info(f"First run in NeonDB for portal '{portal_id}'. Initializing state with {len(current_listings)} listings.")
                cls.save_listings(portal_id, current_listings)
                cls.save_new_listings(portal_id, [])
                return []

            previous_ids = {str(item.get("jobid")) for item in previous_listings if item.get("jobid")}
            
            new_listings = []
            for item in current_listings:
                job_id = str(item.get("jobid"))
                if job_id and job_id not in previous_ids:
                    new_listings.append(item)

            cls.save_listings(portal_id, current_listings)
            cls.save_new_listings(portal_id, new_listings)
            return new_listings
        finally:
            session.close()


class JobStorage:
    """
    Unified storage manager that automatically dispatches calls to NeonDB
    when DATABASE_URL is configured, or falls back to JSON file storage.
    """
    @classmethod
    def is_db_enabled(cls) -> bool:
        return get_database_url() is not None

    @classmethod
    def get_all_portals_metadata(cls, adapters: List[Any]) -> List[Dict[str, Any]]:
        if cls.is_db_enabled():
            return DBJobStorage.get_all_portals_metadata(adapters)
        return FileJSONJobStorage.get_all_portals_metadata(adapters)

    @classmethod
    def get_previous_listings(cls, portal_id: str) -> List[Dict[str, Any]]:
        if cls.is_db_enabled():
            return DBJobStorage.get_previous_listings(portal_id)
        return FileJSONJobStorage.get_previous_listings(portal_id)

    @classmethod
    def get_new_listings(cls, portal_id: str) -> List[Dict[str, Any]]:
        if cls.is_db_enabled():
            return DBJobStorage.get_new_listings(portal_id)
        return FileJSONJobStorage.get_new_listings(portal_id)

    @classmethod
    def get_run_status(cls, portal_id: str) -> Optional[Dict[str, Any]]:
        if cls.is_db_enabled():
            return DBJobStorage.get_run_status(portal_id)
        return FileJSONJobStorage.get_run_status(portal_id)

    @classmethod
    def save_run_status(cls, portal_id: str, status: str, error_message: Optional[str] = None, scraped_count: int = 0) -> None:
        if cls.is_db_enabled():
            DBJobStorage.save_run_status(portal_id, status, error_message, scraped_count)
        else:
            FileJSONJobStorage.save_run_status(portal_id, status, error_message, scraped_count)

    @classmethod
    def save_listings(cls, portal_id: str, listings: List[Dict[str, Any]]) -> None:
        if cls.is_db_enabled():
            DBJobStorage.save_listings(portal_id, listings)
        else:
            FileJSONJobStorage.save_listings(portal_id, listings)

    @classmethod
    def save_new_listings(cls, portal_id: str, listings: List[Dict[str, Any]]) -> None:
        if cls.is_db_enabled():
            DBJobStorage.save_new_listings(portal_id, listings)
        else:
            FileJSONJobStorage.save_new_listings(portal_id, listings)

    @classmethod
    def diff_and_update(cls, portal_id: str, current_listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if cls.is_db_enabled():
            return DBJobStorage.diff_and_update(portal_id, current_listings)
        return FileJSONJobStorage.diff_and_update(portal_id, current_listings)


# Alias JSONJobStorage to JobStorage for seamless compatibility across imports
JSONJobStorage = JobStorage
