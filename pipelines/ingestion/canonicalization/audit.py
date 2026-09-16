import re
import statistics
import unicodedata
from collections import Counter, defaultdict

from ..openfoodfacts.config import IMAGE_HOSTS, safe_url
from .rules import ENTITY, TEXT_FIELDS, normalize_quantity, nutrition_issues, placeholder_reason
from .transform import decode_row


def image_summary(images: list[dict]) -> dict:
    valid = [image for image in images if image["image_valid"]]
    statuses = Counter(image["image_validation_status"] for image in images)
    result = {
        "valid": len(valid),
        "missing": sum(statuses[s] for s in ("no_path", "missing_file")),
        "invalid": sum(
            count
            for status, count in statuses.items()
            if status not in {"valid", "no_path", "missing_file"}
        ),
        "statuses": dict(sorted(statuses.items())),
        "formats": dict(sorted(Counter(image["image_format"] for image in valid).items())),
    }
    for key in ("image_width", "image_height", "image_size_bytes"):
        values = [image[key] for image in valid]
        result[key] = (
            {
                "min": min(values),
                "max": max(values),
                "median": statistics.median(values),
                "mean": round(statistics.mean(values), 2),
            }
            if values
            else None
        )
    return result


def missing_counts(rows: list[dict]) -> dict:
    return (
        {field: sum(row[field] in ("", "{}", "[]") for row in rows) for field in rows[0]}
        if rows
        else {}
    )


def duplicates(rows: list[dict], field: str) -> dict:
    counts = Counter(row[field] for row in rows)
    repeated = {key: count for key, count in counts.items() if count > 1}
    return {"extra_rows": sum(count - 1 for count in repeated.values()), "values": repeated}


def audit_rows(rows: list[dict], columns: list[str], images: list[dict]) -> dict:
    decoded = [decode_row(row) for row in rows]
    report = {
        "rows": len(rows),
        "columns": columns,
        "column_count": len(columns),
        "duplicate_product_ids": duplicates(rows, "product_id"),
        "duplicate_barcodes": duplicates(rows, "barcode"),
        "duplicate_rows": len(rows) - len({tuple(row.items()) for row in rows}),
        "identity_mismatches": [
            r["product_id"] for r in rows if r["product_id"] != "OFF_" + r["barcode"]
        ],
        "missing_values": missing_counts(rows),
        "images": image_summary(images),
        "malformed_image_urls": [
            r["product_id"]
            for r in rows
            if r["image_url"] and not safe_url(r["image_url"], IMAGE_HOSTS)
        ],
        "text": {},
        "casing_variants": {},
    }
    for field in TEXT_FIELDS:
        report["text"][field] = {
            "whitespace_rows": sum(r[field] != " ".join(r[field].split()) for r in rows),
            "non_nfc_rows": sum(r[field] != unicodedata.normalize("NFC", r[field]) for r in rows),
            "html_entity_rows": sum(bool(ENTITY.search(r[field])) for r in rows),
            "replacement_character_rows": sum("\ufffd" in r[field] for r in rows),
            "whole_placeholder_rows": sum(
                bool(r[field]) and placeholder_reason(r[field]) is not None for r in rows
            ),
            "placeholder_values": dict(
                Counter(
                    r[field] for r in rows if r[field] and placeholder_reason(r[field]) is not None
                )
            ),
        }
    for field in ("product_name", "brand", "category", "country"):
        groups = defaultdict(set)
        for row in rows:
            groups[row[field].casefold()].add(row[field])
        variants = [sorted(group) for group in groups.values() if len(group) > 1]
        report["casing_variants"][field] = {"groups": len(variants), "examples": variants[:10]}
    report["categories"] = {
        "tagged_display_rows": sum(bool(re.match(r"[a-z]{2}:", r["category"])) for r in rows),
        "placeholder_tag_rows": sum(
            any(placeholder_reason(tag) for tag in r["categories_tags"]) for r in decoded
        ),
        "ordered_arrow_hierarchies": sum(">" in r["category"] for r in rows),
    }
    report["multiple_country_rows"] = sum(len(r["countries_tags"]) > 1 for r in decoded)
    report["quantity"] = {
        "unit_unspecified_rows": sum(bool(re.fullmatch(r"[\d.,]+", r["quantity"])) for r in rows),
        "simple_format_changes": sum(
            normalize_quantity(r["quantity"]) != r["quantity"] for r in rows
        ),
        "examples": [list(pair) for pair in Counter(r["quantity"] for r in rows).most_common(10)],
    }
    review = [
        (r["product_id"], nutrition_issues(r["nutrition"], r["nutrition_basis"])) for r in decoded
    ]
    report["nutrition_review"] = {
        "products": sum(bool(issues) for _, issues in review),
        "values": sum(len(issues) for _, issues in review),
        "examples": [{"product_id": pid, "issues": issues} for pid, issues in review if issues][
            :10
        ],
        "action": "Retain source values; flag for review without guessing corrections",
    }
    return report
