from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Look for .env in the backend directory regardless of cwd
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # Application
    app_name: str = "AI Financial Investigator"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = (
        "sqlite:////tmp/financial_investigator.db"
        if os.environ.get("VERCEL") == "1"
        else f"sqlite:///{BASE_DIR}/data/financial_investigator.db"
    )

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
