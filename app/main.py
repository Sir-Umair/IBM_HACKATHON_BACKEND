"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
import os
import shutil

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, is_serverless
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
    """Startup: ensure DB and data directory exist with zero cold-start crashes."""
    try:
        if is_serverless():
            tmp_db = Path("/tmp/financial_investigator.db")
            if not tmp_db.exists():
                # Search possible locations for seed database
                candidates = [
                    Path(__file__).resolve().parent.parent / "data" / "financial_investigator.db",
                    Path("/var/task/data/financial_investigator.db"),
                    Path("/var/task/backend/data/financial_investigator.db"),
                ]
                for cand in candidates:
                    if cand.exists():
                        try:
                            shutil.copyfile(cand, tmp_db)
                            logger.info("Copied seed database to %s", tmp_db)
                            break
                        except Exception as exc:
                            logger.warning("Could not copy seed DB: %s", exc)
        else:
            local_data = Path(__file__).resolve().parent.parent / "data"
            local_data.mkdir(parents=True, exist_ok=True)

        init_db()
        logger.info("AI Financial Investigator started — database ready")
    except Exception as exc:
        logger.warning("Lifespan startup non-fatal warning: %s", exc)

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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    origin = request.headers.get("origin") or "*"
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"},
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )

# Register routers
app.include_router(dashboard_router)
app.include_router(transactions_router)
app.include_router(investigations_router)
app.include_router(investigate_router)


@app.get("/")
def root():
    return {
        "service": "AI Financial Investigator",
        "version": "1.0.0",
        "status": "online",
        "environment": "serverless" if is_serverless() else "standard",
        "docs": "/docs",
    }
