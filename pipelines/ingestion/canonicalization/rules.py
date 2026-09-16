import html
import math
import re
import unicodedata

TEXT_FIELDS = (
    "product_name",
    "brand",
    "category",
    "ingredients",
    "country",
    "packaging",
    "quantity",
    "serving_size",
)
LIST_FIELDS = ("categories_tags", "brands_tags", "countries_tags", "labels", "allergens")
JSON_FIELDS = ("nutrition", *LIST_FIELDS)
PLACEHOLDERS = {
    "null",
    "none",
    "nan",
    "undefined",
    "unknown",
    "n/a",
    "na",
    "-",
    "not applicable",
    "not-applicable",
    "unavailable",
    "not available",
}
ENTITY = re.compile(r"&(?:[a-zA-Z]+|#[0-9]+|#x[0-9a-fA-F]+);")
MARKUP = re.compile(r"</?(b|i|p|br|span|strong|em|div|sup|sub)\b[^>]*>", re.I)
ARTIFACTS = str.maketrans({"\u200b": "", "\ufeff": "", "\u00ad": ""})


def clean_text(value: str) -> str:
    value = ENTITY.sub(lambda match: html.unescape(match[0]), value)
    value = MARKUP.sub(lambda match: " " if match[1].lower() in {"p", "div", "br"} else "", value)
    # Preserve ZWJ/ZWNJ, accents, mathematical symbols, percentages, and display casing.
    value = unicodedata.normalize("NFC", value.translate(ARTIFACTS))
    return " ".join(value.split())


def search_form(value: str) -> str:
    return unicodedata.normalize("NFC", clean_text(value).casefold())


def placeholder_reason(value: str) -> str | None:
    token = re.sub(r"^[a-z]{2}:", "", search_form(value))
    if not token:
        return "not_provided"
    if token not in PLACEHOLDERS:
        return None
    if token in {"not applicable", "not-applicable"}:
        return "source_not_applicable"
    if token in {"unavailable", "not available"}:
        return "source_unavailable"
    return "source_placeholder"  # N/A alone is ambiguous; never infer not-applicable from it.


def display_value(value: str, *, multiple: bool = False) -> str:
    value = clean_text(value)
    tokens = value.split(",") if multiple else [value]
    return ", ".join(clean_text(t) for t in tokens if placeholder_reason(t) is None)


def normalized_brands(value: str) -> list[str]:
    return sorted(
        {search_form(token) for token in value.split(",") if not placeholder_reason(token)}
    )


def normalized_tags(tags: list[str], display: str) -> list[str]:
    usable = sorted({search_form(tag) for tag in tags if not placeholder_reason(tag)})
    if usable:
        return usable
    # OFF category arrays are not ordered hierarchies: never infer a leaf from the last item.
    return sorted(
        {
            search_form(token)
            if re.match(r"^[a-z]{2}:", search_form(token))
            else f"text:{search_form(token)}"
            for token in display.split(",")
            if not placeholder_reason(token)
        }
    )


def normalize_quantity(value: str) -> str:
    value = search_form(value)
    match = re.fullmatch(
        r"(\d+(?:[.,]\d+)?)\s*(kg|g|mg|ml|cl|dl|l|litre|liter|litres|liters|oz|lb)(\s+[e℮])?", value
    )
    if not match:
        return value  # Preserve multipacks, counts, estimated weights and mixed-unit declarations.
    unit = "l" if match[2] in {"litre", "liter", "litres", "liters"} else match[2]
    return f"{match[1]} {unit}{match[3] or ''}"


def nutrition_issues(nutrition: dict, basis: str) -> list[str]:
    issues = []
    for key, value in nutrition.items():
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError("Nutrition values must be numbers, not strings or booleans")
        if not math.isfinite(value) or value < 0:
            raise ValueError("Nutrition contains a negative or non-finite value")
        if key.endswith("_100g") and not key.startswith("energy") and value > 100:
            reason = "over_100g_per_100g" if basis == "100g" else "high_value_basis_review"
            issues.append(f"nutrition:{key}:{reason}")
    return sorted(issues)


def search_text(record: dict) -> str:
    # Field labels and order are a versioned contract. No mutable operational retail facts.
    fields = [
        ("Product", record["product_name"]),
        ("Brand", record["brand"]),
        ("Categories", ", ".join(record["category_normalized"])),
        ("Ingredients", record["ingredients"]),
        ("Countries", ", ".join(record["country_normalized"])),
        ("Packaging", record["packaging"]),
        ("Quantity", record["quantity"]),
    ]
    return "\n".join(f"{label}: {value}" for label, value in fields if value)
