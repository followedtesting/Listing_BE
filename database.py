import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

class JobListingModel(Base):
    """
    Stores all active job listings for each portal in NeonDB.
    """
    __tablename__ = "job_listings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    portal_id = Column(String(100), index=True, nullable=False)
    jobid = Column(String(255), index=True, nullable=False)
    role_name = Column(Text, nullable=False)
    job_listing_link = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('portal_id', 'jobid', name='_portal_job_uc'),
    )

class NewJobListingModel(Base):
    """
    Stores newly detected job listings diff for each portal in NeonDB.
    """
    __tablename__ = "new_job_listings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    portal_id = Column(String(100), index=True, nullable=False)
    jobid = Column(String(255), index=True, nullable=False)
    role_name = Column(Text, nullable=False)
    job_listing_link = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AdapterRunModel(Base):
    """
    Stores the last execution run status and timestamp for each adapter/portal in NeonDB.
    """
    __tablename__ = "adapter_runs"

    portal_id = Column(String(100), primary_key=True, index=True)
    last_run_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String(20), nullable=False)  # 'success' or 'failed'
    error_message = Column(Text, nullable=True)
    last_scraped_count = Column(Integer, default=0)


class AdapterQueueModel(Base):
    """
    Queue table in NeonDB storing the execution state of each adapter during sequential runs.
    """
    __tablename__ = "adapter_queue"

    portal_id = Column(String(100), primary_key=True, index=True)
    portal_name = Column(String(255), nullable=False)
    order_index = Column(Integer, default=0, index=True, nullable=False)
    status = Column(String(30), default="idle", index=True, nullable=False)  # 'idle', 'pending', 'running', 'success', 'failed'
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=2)
    last_scraped_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


engine = None
SessionLocal = None

def get_database_url() -> Optional[str]:
    url = settings.DATABASE_URL.strip() if settings.DATABASE_URL else ""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url if url else None

def init_db():
    global engine, SessionLocal
    db_url = get_database_url()
    
    if not db_url:
        logger.info("No DATABASE_URL configured. Database storage disabled, using JSON storage fallback.")
        return
        
    try:
        logger.info("Initializing NeonDB PostgreSQL connection engine...")
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)
        
        # Ensure new column exists on pre-existing table in PostgreSQL
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE adapter_queue ADD COLUMN IF NOT EXISTS order_index INTEGER DEFAULT 0;"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_adapter_queue_order_index ON adapter_queue (order_index);"))
                conn.commit()
        except Exception as mig_err:
            logger.warning(f"Note on order_index column migration: {mig_err}")

        logger.info("NeonDB database schema initialized successfully! Tables created/verified.")
    except Exception as e:
        logger.error(f"Failed to initialize NeonDB connection: {e}", exc_info=True)
        engine = None
        SessionLocal = None

def get_db_session() -> Optional[Session]:
    if SessionLocal is None:
        return None
    try:
        return SessionLocal()
    except Exception as e:
        logger.error(f"Failed to create DB session: {e}")
        return None
