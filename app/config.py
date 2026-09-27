from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path
import os


def is_serverless() -> bool:
    """Detect if running in Vercel, AWS Lambda, or a serverless container."""
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("VERCEL_ENV")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("LAMBDA_TASK_ROOT")
    )


# Project root directory (backend folder)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Look for .env in the backend directory regardless of cwd
_ENV_FILE = PROJECT_ROOT / ".env"


def _get_default_database_url() -> str:
    # 1. Direct environment override
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    # 2. Serverless (Vercel / Lambda): writable /tmp storage to prevent read-only filesystem crash
    if is_serverless():
        return "sqlite:////tmp/financial_investigator.db"

    # 3. Local development
    local_db = PROJECT_ROOT / "data" / "financial_investigator.db"
    return f"sqlite:///{local_db.as_posix()}"


class Settings(BaseSettings):
    # Application
    app_name: str = "AI Financial Investigator"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = _get_default_database_url()

    # CORS
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "*",
    ]

    # Google Gemini free tier — https://aistudio.google.com/app/apikey
    # Key can be set via GOOGLE_API_KEY env var or in backend/.env
    google_api_key: str = "AIzaSyAQ.Ab8RN6LtDb_eBtSwI3YPtBh-nDeMIdrkFBxEmWO90JOyDVYN-g"
    google_model_id: str = "gemini-2.0-flash"

    # Upload limits
    max_upload_size_mb: int = 10

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
