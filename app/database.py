from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.engine import Engine
from app.config import get_settings, is_serverless
import sqlite3
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


# SQLite pragma configurations with safe fallback for serverless
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # In serverless/read-only or tmpfs, WAL can cause locked database or shm errors
            if is_serverless():
                cursor.execute("PRAGMA journal_mode=MEMORY")
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.execute("PRAGMA synchronous=OFF")
            else:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
        except Exception as exc:
            logger.debug("SQLite pragma non-fatal warning: %s", exc)


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=settings.debug,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


_db_ready = False


def ensure_db_ready():
    """Ensure database schema is created and auto-seed initial data if empty."""
    global _db_ready
    if _db_ready:
        return
    _db_ready = True
    try:
        from app.models import db_models  # noqa: F401 - registers models
        Base.metadata.create_all(bind=engine)

        # Check if database is empty; if so, populate initial seed data
        db = SessionLocal()
        try:
            count = db.query(db_models.Transaction).count()
            if count == 0:
                logger.info("Database empty, initializing seed data...")
                try:
                    import seed_data
                    seed_data.seed_all()
                    logger.info("Seed data successfully populated.")
                except Exception as s_err:
                    logger.warning("Auto-seed non-fatal error: %s", s_err)
        except Exception as q_err:
            logger.warning("Error checking transaction table: %s", q_err)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Database ensure_db_ready warning: %s", exc)


def get_db():
    """FastAPI dependency that provides a database session."""
    ensure_db_ready()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and seed data if needed."""
    ensure_db_ready()
