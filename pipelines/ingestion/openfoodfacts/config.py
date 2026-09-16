from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]
SOURCE_URL = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"
IMAGE_HOSTS = {"images.openfoodfacts.org", "openfoodfacts-images.s3.eu-west-3.amazonaws.com"}
SOURCE_HOSTS = {"static.openfoodfacts.org", "openfoodfacts-ds.s3.eu-west-3.amazonaws.com"}


def safe_url(value: str, hosts: set[str]) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname in hosts
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(c.isspace() for c in value)
            and ".." not in parsed.path
            and "%" not in parsed.path
        )
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="OFF_", extra="ignore", hide_input_in_errors=True
    )

    target_products: int = Field(default=3000, ge=1, le=10_000)
    max_raw_records: int = Field(default=12_000, ge=1, le=100_000)
    source_url: str = SOURCE_URL
    source_format: Literal["jsonl", "tsv", "csv"] = "jsonl"
    source_file: str = ""
    source_retrieved_at: str = ""
    snapshot: str = "initial"
    data_dir: Path = ROOT / "data"
    max_source_bytes: int = Field(default=134_217_728, ge=1_048_576, le=536_870_912)
    download_images: bool = True
    image_timeout: float = Field(default=20, ge=1, le=120)
    max_retries: int = Field(default=2, ge=0, le=5)
    image_workers: int = Field(default=4, ge=1, le=4)
    image_requests_per_second: float = Field(default=4, gt=0, le=4)
    max_image_bytes: int = Field(default=5_242_880, ge=1024, le=20_971_520)
    user_agent: str = "RetailVision/0.2 (academic Product Master ingestion)"

    @field_validator("source_url")
    @classmethod
    def official_source(cls, value: str) -> str:
        if not safe_url(value, SOURCE_HOSTS):
            raise ValueError("Use a credential-free HTTPS official export URL or --source-file")
        return value

    @field_validator("snapshot")
    @classmethod
    def snapshot_name(cls, value: str) -> str:
        if not value or not all(c.isascii() and (c.isalnum() or c in "-_") for c in value):
            raise ValueError("Snapshot must contain only ASCII letters, digits, hyphen, underscore")
        return value

    @field_validator("source_retrieved_at")
    @classmethod
    def retrieval_date(cls, value: str) -> str:
        if value:
            from datetime import datetime

            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Retrieval timestamp needs a timezone")
        return value

    @model_validator(mode="after")
    def sufficient_sample(self):
        if self.max_raw_records < self.target_products:
            raise ValueError("OFF_MAX_RAW_RECORDS must be at least OFF_TARGET_PRODUCTS")
        self.data_dir = self.data_dir.resolve()
        return self
