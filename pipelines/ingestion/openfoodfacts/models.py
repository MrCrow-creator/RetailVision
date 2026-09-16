import math
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import IMAGE_HOSTS, safe_url
from .storage import canonical

NUTRIENTS = (
    "energy-kj_100g",
    "energy-kcal_100g",
    "fat_100g",
    "saturated-fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
)


def text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(unicodedata.normalize("NFC", value).split())
    return "" if value.casefold() in {"nan", "null", "none", "n/a"} else value


def tags(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    return sorted({text(item) for item in value if text(item)}) if isinstance(value, list) else []


def normalize_barcode(value: Any) -> str:
    # Never coerce float/scientific notation: lost precision/leading zeros cannot be recovered.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("invalid_barcode")
    code = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,14}", code) or not code.strip("0"):
        raise ValueError("invalid_barcode")
    code = code.lstrip("0")
    if len(code) <= 8:
        return code.zfill(8)
    if len(code) <= 13:
        return code.zfill(13)
    return code


def product_id(value: Any) -> str:
    return f"OFF_{normalize_barcode(value)}"


def checksum_valid(code: str) -> bool:
    total = sum(int(digit) * (3 if i % 2 == 0 else 1) for i, digit in enumerate(code[-2::-1]))
    return (10 - total % 10) % 10 == int(code[-1])


def image_url(raw: dict) -> str:
    # AWS holds raw uploaded images, not revisioned selected/cropped images.
    # Use the actual selected front imgid; never assume image 1 is a front image.
    images = raw.get("images")
    if isinstance(images, dict):
        language = text(raw.get("lang")) or "en"
        # Current schema (1002+): images.selected.front.<language>.
        selected_images = images.get("selected")
        if isinstance(selected_images, dict) and isinstance(selected_images.get("front"), dict):
            images = {f"front_{lang}": image for lang, image in selected_images["front"].items()}
        keys = list(dict.fromkeys([f"front_{language}", "front_en", *sorted(images)]))
        for key in keys:
            selected = images.get(key)
            if not key.startswith("front_") or not isinstance(selected, dict):
                continue
            image_id = str(selected.get("imgid", ""))
            if re.fullmatch(r"[0-9]+", image_id):
                code = normalize_barcode(raw.get("code", raw.get("barcode"))).zfill(13)
                folder = f"{code[:3]}/{code[3:6]}/{code[6:9]}/{code[9:]}"
                return (
                    "https://openfoodfacts-images.s3.eu-west-3.amazonaws.com/data/"
                    f"{folder}/{image_id}.400.jpg"
                )
    for key in ("image_front_url", "image_url", "image_front_small_url", "image_small_url"):
        url = text(raw.get(key))
        if safe_url(url, IMAGE_HOSTS):
            return url
    return ""


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    product_id: str
    barcode: str
    product_name: str = Field(min_length=1)
    brand: str = ""
    category: str = ""
    ingredients: str = ""
    nutrition: dict[str, float] = Field(default_factory=dict)
    nutrition_basis: str = ""
    nutrition_source: str = ""
    country: str = ""
    packaging: str = ""
    image_url: str = ""
    image_path: str = ""
    quantity: str = ""
    serving_size: str = ""
    categories_tags: list[str] = Field(default_factory=list)
    brands_tags: list[str] = Field(default_factory=list)
    countries_tags: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    barcode_checksum_valid: bool
    image_status: Literal["pending", "downloaded", "failed", "missing", "not_checked"] = "pending"
    data_quality_score: float = Field(default=0, ge=0, le=1)
    source: Literal["Open Food Facts"] = "Open Food Facts"
    source_product_url: str

    @field_validator("product_name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not text(value):
            raise ValueError("missing_product_name")
        return text(value)

    @model_validator(mode="after")
    def stable_identity(self):
        if normalize_barcode(self.barcode) != self.barcode:
            raise ValueError("barcode must be canonical")
        if self.product_id != product_id(self.barcode):
            raise ValueError("product_id must match canonical barcode")
        if self.image_url and not safe_url(self.image_url, IMAGE_HOSTS):
            raise ValueError("unsupported image URL")
        return self

    def score(self, usable_image: bool) -> float:
        # Seven equally weighted presence flags. Identity/name required, remaining five optional.
        return round(
            sum(
                [
                    True,
                    True,
                    bool(self.brand),
                    bool(self.category),
                    usable_image,
                    bool(self.ingredients),
                    bool(self.nutrition),
                ]
            )
            / 7,
            4,
        )


def normalize(raw: Any) -> tuple[Product | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["malformed_record"]
    errors = []
    try:
        code = normalize_barcode(raw.get("code", raw.get("barcode")))
    except ValueError:
        errors.append("invalid_barcode")
        code = ""
    name = text(raw.get("product_name")) or text(raw.get("product_name_en"))
    if not name:
        errors.append("missing_product_name")
    if errors:
        return None, errors
    nutriments = raw.get("nutriments")
    nutriments = nutriments if isinstance(nutriments, dict) else raw
    basis = "100g_or_100ml"
    nutrition_source = "off_legacy_as_sold"
    # Current schema (1003+): the official aggregated set already has normalized units.
    current = raw.get("nutrition")
    aggregated = current.get("aggregated_set") if isinstance(current, dict) else None
    if isinstance(aggregated, dict):
        nutriments = {}
        basis = text(aggregated.get("per"))
        nutrition_source = "off_aggregated_as_sold"
        nutrients = aggregated.get("nutrients")
        if (
            aggregated.get("preparation") == "as_sold"
            and basis in {"100g", "100ml"}
            and isinstance(nutrients, dict)
        ):
            for field in NUTRIENTS:
                nutrient_id = field.removesuffix("_100g")
                entry = nutrients.get(nutrient_id)
                unit = (
                    "kJ"
                    if nutrient_id == "energy-kj"
                    else ("kcal" if nutrient_id == "energy-kcal" else "g")
                )
                if isinstance(entry, dict) and entry.get("unit") == unit:
                    nutriments[field] = entry.get("value")
    nutrition = {}
    for field in NUTRIENTS:
        value = nutriments.get(field)
        try:
            if value is not None and not isinstance(value, bool):
                number = float(value)
                if math.isfinite(number) and number >= 0:
                    nutrition[field] = number
        except (TypeError, ValueError, OverflowError):
            pass
    categories = tags(raw.get("categories_tags"))
    countries = tags(raw.get("countries_tags"))
    product = Product(
        product_id=product_id(code),
        barcode=code,
        product_name=name,
        brand=text(raw.get("brands")),
        category=text(raw.get("categories")) or ", ".join(categories),
        ingredients=text(raw.get("ingredients_text")) or text(raw.get("ingredients_text_en")),
        nutrition=nutrition,
        nutrition_basis=basis if nutrition else "",
        nutrition_source=nutrition_source if nutrition else "",
        country=text(raw.get("countries")) or ", ".join(countries),
        packaging=text(raw.get("packaging")),
        image_url=image_url(raw),
        quantity=text(raw.get("quantity")),
        serving_size=text(raw.get("serving_size")),
        categories_tags=categories,
        countries_tags=countries,
        brands_tags=tags(raw.get("brands_tags")),
        labels=tags(raw.get("labels_tags", raw.get("labels"))),
        allergens=tags(raw.get("allergens_tags", raw.get("allergens"))),
        barcode_checksum_valid=checksum_valid(code),
        source_product_url=f"https://world.openfoodfacts.org/product/{code}",
    )
    product.data_quality_score = product.score(bool(product.image_url))
    return product, []


def preference(product: Product) -> tuple:
    # Whole-record selection avoids constructing contradictory merged ingredient/nutrition facts.
    record = product.model_dump()
    information = sum(bool(v) for v in record.values())
    return (-product.data_quality_score, -information, canonical(record))
