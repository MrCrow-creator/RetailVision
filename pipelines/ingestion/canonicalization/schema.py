from typing import Literal

from pydantic import Field, model_validator

from ..openfoodfacts.models import Product
from .rules import nutrition_issues, search_text


class CanonicalProduct(Product):
    """All 25 Milestone 2 columns plus explicit source, search, review and image fields."""

    source_values: dict[str, str] = Field(default_factory=dict)
    product_name_normalized: str
    brand_normalized: list[str]
    category_normalized: list[str]
    country_normalized: list[str]
    quantity_normalized: str
    search_text: str = Field(min_length=1)
    missing_value_reasons: dict[str, str]
    normalization_issues: list[str]
    nutrition_review_required: bool
    image_available: bool
    image_valid: bool
    image_format: str
    image_width: int | None = Field(default=None, gt=0)
    image_height: int | None = Field(default=None, gt=0)
    image_size_bytes: int | None = Field(default=None, ge=0)
    image_sha256: str
    image_validation_status: Literal[
        "valid",
        "no_path",
        "unsafe_path",
        "missing_file",
        "unreadable",
        "oversize",
        "unsupported_format",
        "invalid_dimensions",
        "corrupt",
    ]

    @model_validator(mode="after")
    def canonical_contract(self):
        if self.image_valid != (self.image_validation_status == "valid"):
            raise ValueError("Image validity and validation status disagree")
        if self.image_valid and not (
            self.image_available
            and self.image_path
            and self.image_width
            and self.image_height
            and self.image_size_bytes
            and len(self.image_sha256) == 64
            and self.image_format in {"JPEG", "PNG", "WEBP"}
        ):
            raise ValueError("A valid image requires a path and complete metadata")
        if not self.image_valid and self.image_path:
            raise ValueError("Invalid image paths cannot be published as usable paths")
        if self.search_text != search_text(self.model_dump()):
            raise ValueError("Non-deterministic search text")
        if self.data_quality_score != self.score(self.image_valid):
            raise ValueError("Completeness score disagrees with cleaned fields")
        if self.nutrition_review_required != bool(
            nutrition_issues(self.nutrition, self.nutrition_basis)
        ):
            raise ValueError("Nutrition review flag disagrees with source values")
        return self
