from datetime import date

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..openfoodfacts.config import ROOT


class RetailSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="SYNTHETIC_", extra="ignore", hide_input_in_errors=True
    )

    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    as_of_date: date = date(2026, 9, 17)
    store_count: int = Field(default=8, ge=2, le=10)
    shelves_per_store: int = Field(default=15, ge=1, le=20)
    supplier_count: int = Field(default=30, ge=1, le=40)
    promotion_count: int = Field(default=200, ge=1, le=300)
    placement_count: int = Field(default=6500, ge=30, le=20_000)
    max_stores_per_product: int = Field(default=4, ge=1, le=10)
    promotion_rate: float = Field(default=0.15, ge=0.10, le=0.20)
    high_sales_threshold: int = Field(default=90, ge=30)
    low_sales_threshold: int = Field(default=15, ge=0)

    @model_validator(mode="after")
    def thresholds(self):
        if self.low_sales_threshold >= self.high_sales_threshold:
            raise ValueError("Low-sales threshold must be below the high-sales threshold")
        return self

    def check_scale(self, product_count: int) -> None:
        maximum = product_count * min(self.max_stores_per_product, self.store_count)
        if not product_count <= self.placement_count <= maximum:
            raise ValueError(
                f"Placement count must be between {product_count} and {maximum} for this input"
            )
