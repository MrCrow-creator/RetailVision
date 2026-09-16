import csv
import io
import json

import pytest
from pydantic import ValidationError

from ingestion.openfoodfacts.models import Product, normalize, normalize_barcode, product_id
from ingestion.openfoodfacts.pipeline import export_csv, normalize_sample


@pytest.mark.parametrize(
    "value,expected",
    [
        ("8901234567890", "8901234567890"),
        (8901234567890, "8901234567890"),
        (" 8901234567890 ", "8901234567890"),
        ("034000470693", "0034000470693"),
        ("0034000470693", "0034000470693"),
        ("0000001234567", "01234567"),
    ],
)
def test_barcode_normalization_preserves_off_identity(value, expected):
    assert normalize_barcode(value) == expected
    assert normalize_barcode(expected) == expected
    assert product_id(value) == f"OFF_{expected}"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "abc123",
        "0" * 13,
        "1" * 15,
        True,
        8901234567890.0,
        "8901234567890.0",
        "8.90123456789e12",
    ],
)
def test_invalid_and_lossy_barcodes_are_rejected(value):
    product, errors = normalize({"code": value, "product_name": "Test item"})
    assert product is None
    assert errors == ["invalid_barcode"]


def test_optional_fields_and_whitespace():
    raw = {"code": "8901234567890", "product_name": "  Test\tproduct \n", "nutriments": None}
    product, errors = normalize(raw)
    assert errors == []
    assert product.product_name == "Test product"
    assert product.ingredients == ""
    assert product.nutrition == {}
    assert product.data_quality_score == round(2 / 7, 4)
    assert normalize(raw)[0].product_id == product.product_id


def test_required_fields_and_final_schema():
    assert normalize({"code": "8901234567890", "product_name": "  "})[1] == ["missing_product_name"]
    product = normalize({"code": "8901234567890", "product_name": "Test"})[0]
    record = product.model_dump()
    for field in ("product_id", "barcode", "product_name"):
        invalid = {k: v for k, v in record.items() if k != field}
        with pytest.raises(ValidationError):
            Product.model_validate(invalid)
    with pytest.raises(ValidationError):
        Product.model_validate({**record, "product_id": "OFF_12345678"})


def test_deduplication_is_order_independent_and_selects_complete_record(tmp_path):
    partial = {"code": "034000470693", "product_name": "Test product"}
    complete = {
        **partial,
        "code": "0034000470693",
        "brands": " Test   Brand ",
        "categories": "Snacks",
        "ingredients_text": "Cocoa",
    }
    results = []
    for index, rows in enumerate(([partial, complete], [complete, partial])):
        path = tmp_path / f"{index}.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        products, counts = normalize_sample(path)
        assert counts["duplicates_removed"] == 1
        assert len(products) == 1
        assert products[0].brand == "Test Brand"
        results.append(export_csv(products))
    assert results[0] == results[1]
    row = list(csv.DictReader(io.StringIO(results[0].decode())))[0]
    assert row["barcode"] == "0034000470693"
    assert row["product_id"] == "OFF_0034000470693"


@pytest.mark.parametrize(
    "images",
    [
        {"front_en": {"imgid": "7", "rev": "10"}},
        {"selected": {"front": {"en": {"imgid": 7, "rev": 10}}}},
    ],
)
def test_current_and_legacy_front_image_selection(images):
    product, _ = normalize({"code": "8901234567890", "product_name": "Test", "images": images})
    assert product.image_url == (
        "https://openfoodfacts-images.s3.eu-west-3.amazonaws.com/data/890/123/456/7890/7.400.jpg"
    )


def test_current_nutrition_does_not_confuse_units_or_preparation():
    raw = {
        "code": "8901234567890",
        "product_name": "Test",
        "nutrition": {
            "aggregated_set": {
                "preparation": "as_sold",
                "per": "100ml",
                "nutrients": {
                    "sugars": {"value": 2, "unit": "g"},
                    "salt": {"value": 300, "unit": "mg"},
                    "energy-kj": {"value": 80, "unit": "kJ"},
                },
            }
        },
    }
    product, _ = normalize(raw)
    assert product.nutrition == {"sugars_100g": 2, "energy-kj_100g": 80}
    assert product.nutrition_basis == "100ml"
    raw["nutrition"]["aggregated_set"]["preparation"] = "prepared"
    assert normalize(raw)[0].nutrition == {}


def test_short_barcode_image_path_is_padded_without_changing_product_id():
    product, _ = normalize(
        {
            "code": "00000758",
            "product_name": "Test",
            "images": {"selected": {"front": {"en": {"imgid": 1}}}},
        }
    )
    assert product.product_id == "OFF_00000758"
    assert product.image_url.endswith("/000/000/000/0758/1.400.jpg")


def test_legacy_nutrition_handles_zero_and_malformed_optional_values():
    raw = {
        "code": "8901234567890",
        "product_name": "Test",
        "nutriments": {
            "sugars_100g": "0",
            "salt_100g": "nan",
            "fat_100g": -2,
            "proteins_100g": [10],
            "fiber_100g": True,
        },
    }
    assert normalize(raw)[0].nutrition == {"sugars_100g": 0}


def test_invalid_image_url_is_optional_and_not_fetched():
    raw = {"code": "8901234567890", "product_name": "Test", "image_url": "http://127.0.0.1/a.jpg"}
    assert normalize(raw)[0].image_url == ""
