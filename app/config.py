from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str = Field("", env=("COAGENT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    anthropic_model: str = "claude-3.5"  # supported free models: claude-3.5, claude-instant-1, claude-4-mini
    database_url: str = "sqlite:///./studymate.db"
    app_timezone: str = "Asia/Dubai"
    upload_dir: str = "uploads"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
