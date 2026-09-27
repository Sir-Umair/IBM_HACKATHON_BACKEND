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


def get_db():
    """FastAPI dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables if they do not exist, wrapped in safe try/except."""
    try:
        from app.models import db_models  # noqa: F401 - registers models
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logger.warning("Database init_db non-fatal warning: %s", exc)
