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
    """Ensure database schema is created and initial seed data is loaded ONLY ONCE on initial deployment."""
    global _db_ready
    if _db_ready:
        return
    _db_ready = True
    try:
        from app.models import db_models  # noqa: F401 - registers models
        Base.metadata.create_all(bind=engine)

        db = SessionLocal()
        try:
            # Check if this database has already been initialized
            init_setting = db.query(db_models.SystemSetting).filter_by(key="system_initialized").first()
            purged_setting = db.query(db_models.SystemSetting).filter_by(key="user_purged").first()

            if not init_setting:
                # First time ever running against this database file
                tx_count = db.query(db_models.Transaction).count()
                if tx_count == 0 and (not purged_setting or purged_setting.value != "true"):
                    logger.info("Brand new database detected — seeding initial baseline dataset...")
                    try:
                        import seed_data
                        seed_data.seed_all()
                        logger.info("Initial seed dataset successfully populated.")
                    except Exception as s_err:
                        logger.warning("Initial auto-seed non-fatal error: %s", s_err)

                # Record initialization in system_settings table so it NEVER re-seeds automatically
                db.merge(db_models.SystemSetting(key="system_initialized", value="true"))
                if not purged_setting:
                    db.merge(db_models.SystemSetting(key="user_purged", value="false"))
                db.commit()
            else:
                logger.debug("Database already initialized; respecting persistent user data and purge states.")
        except Exception as q_err:
            logger.warning("Error checking system_settings or transaction table: %s", q_err)
            db.rollback()
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

