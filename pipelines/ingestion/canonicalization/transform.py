import json
import re

from ..openfoodfacts.config import IMAGE_HOSTS, safe_url
from ..openfoodfacts.models import Product, normalize_barcode
from ..openfoodfacts.storage import canonical
from .rules import (
    JSON_FIELDS,
    LIST_FIELDS,
    TEXT_FIELDS,
    clean_text,
    display_value,
    normalize_quantity,
    normalized_brands,
    normalized_tags,
    nutrition_issues,
    placeholder_reason,
    search_form,
    search_text,
)
from .schema import CanonicalProduct


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def decode_row(row: dict[str, str]) -> dict:
    result = dict(row)
    for field in JSON_FIELDS:
        value = row[field]
        result[field] = (
            json.loads(value, object_pairs_hook=unique_object)
            if placeholder_reason(value) is None
            else ({} if field == "nutrition" else [])
        )
        expected = dict if field == "nutrition" else list
        if not isinstance(result[field], expected):
            raise ValueError(f"Invalid JSON structure: {field}")
        if expected is list and any(not isinstance(item, str) for item in result[field]):
            raise ValueError(f"Non-string tag: {field}")
    nutrition_issues(result["nutrition"], result["nutrition_basis"])
    return result


def cell(value) -> str:
    if isinstance(value, (dict, list)):
        return canonical(value)
    return "" if value is None else str(value)


def transform(row: dict[str, str], image: dict) -> CanonicalProduct:
    # Identity is validated verbatim, never normalized or reassigned in this stage.
    if (
        row["product_id"] != "OFF_" + row["barcode"]
        or normalize_barcode(row["barcode"]) != row["barcode"]
    ):
        raise ValueError("Input identity is not canonical; refusing to change it")
    values = decode_row(row)
    reasons = {}
    issues = []
    for field in TEXT_FIELDS:
        cleaned = display_value(row[field], multiple=field in {"brand", "category", "country"})
        if not cleaned:
            reasons[field] = placeholder_reason(row[field]) or "source_placeholder"
        values[field] = cleaned
        if cleaned != row[field]:
            issues.append(f"cleaned:{field}")
        if "\ufffd" in cleaned:
            issues.append(f"text:{field}:replacement_character_review")
    for field in LIST_FIELDS:
        values[field] = sorted(
            {clean_text(tag) for tag in values[field] if not placeholder_reason(tag)}
        )
    # Display fields retain source language/hierarchy. Tags provide separately derived filter keys.
    categories = normalized_tags(values["categories_tags"], values["category"])
    countries = normalized_tags(values["countries_tags"], values["country"])
    values["image_url"] = clean_text(row["image_url"])
    if values["image_url"] and not safe_url(values["image_url"], IMAGE_HOSTS):
        values["image_url"] = ""
        issues.append("image:invalid_url")
    if not image["image_valid"]:
        values["image_path"] = ""
        reasons["image_path"] = image["image_validation_status"]
        if image["image_validation_status"] != "no_path":
            issues.append(f"image:{image['image_validation_status']}")
            values["image_status"] = "failed"
        elif values["image_status"] == "downloaded":
            values["image_status"] = "failed"
            issues.append("image:downloaded_status_without_path")
    else:
        values["image_status"] = "downloaded"
    if not values["nutrition"]:
        reasons["nutrition"] = "not_provided"
    if not values["image_url"]:
        reasons["image_url"] = "source_unavailable" if row["image_url"] else "not_provided"
    review = nutrition_issues(values["nutrition"], values["nutrition_basis"])
    issues.extend(review)
    if re.fullmatch(r"[\d.,]+", values["quantity"]):
        issues.append("quantity:unit_unspecified")
    base = Product.model_validate(values)
    values = base.model_dump()
    values["data_quality_score"] = base.score(image["image_valid"])
    values.update(
        **image,
        product_name_normalized=search_form(values["product_name"]),
        brand_normalized=normalized_brands(values["brand"]),
        category_normalized=categories,
        country_normalized=countries,
        quantity_normalized=normalize_quantity(values["quantity"]),
        missing_value_reasons=reasons,
        normalization_issues=sorted(issues),
        nutrition_review_required=bool(review),
    )
    values["search_text"] = search_text(values)
    values["source_values"] = {
        field: row[field] for field in Product.model_fields if cell(values[field]) != row[field]
    }
    return CanonicalProduct.model_validate(values)
