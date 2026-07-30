import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_database_url() -> str:
    """Choose a database URL that works for development, packaged builds, and deployment."""
    database_url = (
        os.getenv("DATABASE_URL")
        or os.getenv("STUDYMATE_DATABASE_URL")
        or os.getenv("DB_URL")
    )
    if database_url:
        return database_url

    db_path = os.getenv("STUDYMATE_DB_PATH") or os.getenv("DB_PATH")
    if db_path:
        return f"sqlite:///{Path(db_path).expanduser().resolve().as_posix()}"

    root = Path(__file__).resolve().parent.parent
    try:
        if getattr(sys, "frozen", False):
            base_dir = Path(sys.executable).resolve().parent
        else:
            base_dir = root
    except Exception:
        base_dir = root

    data_dir = base_dir / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    default_db_path = data_dir / "studymate.db"
    legacy_db_path = root / "studymate.db"

    if default_db_path.exists() or not legacy_db_path.exists():
        return f"sqlite:///{default_db_path.resolve().as_posix()}"

    return f"sqlite:///{legacy_db_path.resolve().as_posix()}"


class Settings(BaseSettings):
    anthropic_api_key: str = Field("", env=("COAGENT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    anthropic_model: str = "claude-3.5"  # supported free models: claude-3.5, claude-instant-1, or claude-4-mini
    database_url: str = Field(default_factory=_resolve_database_url)
    app_timezone: str = "Asia/Dubai"
    upload_dir: str = "uploads"
    app_secret: str = Field("", env=("APP_SECRET", "STUDYMATE_APP_SECRET"))
    secret_file: str = Field(".studymate_secret", env=("STUDYMATE_SECRET_FILE",))
    admin_username: str = Field("admin", env=("STUDYMATE_ADMIN_USERNAME", "ADMIN_USERNAME"))
    admin_password: str = Field("", env=("STUDYMATE_ADMIN_PASSWORD", "ADMIN_PASSWORD"))

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
