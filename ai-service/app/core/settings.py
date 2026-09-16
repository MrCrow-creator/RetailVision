from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    node_env: Literal["development", "test", "production"] = "development"
    ai_service_host: str = "127.0.0.1"
    ai_service_port: int = 8000
    ai_reload: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
