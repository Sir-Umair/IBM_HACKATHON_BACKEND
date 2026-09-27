"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_transactions import router as transactions_router
from app.api.routes_investigation import router as investigations_router, investigate_router

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: ensure DB and data directory exist."""
    import os
    if os.environ.get("VERCEL") == "1":
        tmp_db = Path("/tmp/financial_investigator.db")
        if not tmp_db.exists():
            seed_db = Path(__file__).resolve().parent.parent / "data" / "financial_investigator.db"
            if seed_db.exists():
                import shutil
                shutil.copyfile(seed_db, tmp_db)
    else:
        data_dir = Path(__file__).parent.parent.parent / "data"
        data_dir.mkdir(exist_ok=True)
    init_db()
    logger.info("AI Financial Investigator started — database ready")
    yield
    logger.info("Application shutting down")


app = FastAPI(
    title="AI Financial Investigator",
    description="LangGraph-powered financial investigation system",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(dashboard_router)
app.include_router(transactions_router)
app.include_router(investigations_router)
app.include_router(investigate_router)


@app.get("/")
def root():
    return {
        "name": "AI Financial Investigator",
        "version": "1.0.0",
        "docs": "/docs",
    }
