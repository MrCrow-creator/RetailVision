import csv
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from ingestion.canonicalization.images import inspect_image
from ingestion.canonicalization.pipeline import execute
from ingestion.canonicalization.rules import (
    clean_text,
    normalized_brands,
    normalized_tags,
    placeholder_reason,
    search_form,
)
from ingestion.canonicalization.schema import CanonicalProduct
from ingestion.canonicalization.transform import transform
from ingestion.openfoodfacts.models import normalize
from ingestion.openfoodfacts.pipeline import export_csv
from ingestion.openfoodfacts.storage import digest


def source_row(**changes):
    product, errors = normalize(
        {
            "code": "0034000470693",
            "product_name": "Chocolate 70% Cocoa 2 x 50 g",
            "brands": "Test Brand",
            "categories": "en:snacks, en:chocolate-biscuits",
            "categories_tags": ["en:snacks", "en:chocolate-biscuits"],
            "ingredients_text": "Cocoa (70%), sugar, milk",
            "countries": "France, Spain, Belgium",
            "countries_tags": ["en:france", "en:spain", "en:belgium"],
            "nutriments": {"sugars_100g": 3.0},
        }
    )
    assert not errors
    row = next(csv.DictReader(io.StringIO(export_csv([product]).decode())))
    return {**row, **changes}


def write_source(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_row(tmp_path, **changes):
    row = source_row(**changes)
    return transform(row, inspect_image(row["image_path"], tmp_path))


def test_identity_and_meaningful_display_values_preserved(tmp_path):
    record = normalize_row(tmp_path)
    assert record.product_id == "OFF_0034000470693"
    assert record.barcode == "0034000470693"
    assert record.product_name == "Chocolate 70% Cocoa 2 x 50 g"
    assert record.ingredients == "Cocoa (70%), sugar, milk"
    assert record.product_name_normalized == "chocolate 70% cocoa 2 x 50 g"


@pytest.mark.parametrize(
    "changes",
    [
        {"product_id": "random_id"},
        {"barcode": "034000470693"},
        {"barcode": "0034000470693 "},
        {"barcode": "0034000470693.0"},
        {"product_id": ""},
    ],
)
def test_bad_identity_is_rejected_not_repaired(tmp_path, changes):
    with pytest.raises(ValueError):
        normalize_row(tmp_path, **changes)


def test_safe_text_artifacts_unicode_and_original_source_preservation(tmp_path):
    original = "  Cafe\u0301\u200b <b>Dark</b><br>70% &amp; Milk\n2 x 50 g  "
    record = normalize_row(tmp_path, product_name=original)
    assert record.product_name == "Café Dark 70% & Milk 2 x 50 g"
    assert record.source_values["product_name"] == original
    assert clean_text("Salt &lt;0.1g") == "Salt <0.1g"
    assert clean_text("Cocoa 70%, <i>milk</i>, sugar") == "Cocoa 70%, milk, sugar"
    assert clean_text("Nan Pizza, Spinach") == "Nan Pizza, Spinach"
    assert clean_text("👩‍🍳") == "👩‍🍳"  # Don't remove meaningful ZWJ.


def test_brand_normalization_is_conservative_and_multi_valued(tmp_path):
    assert normalized_brands("Nestle, NESTLE, Nestlé, N/A") == ["nestle", "nestlé"]
    assert search_form(" Nestlé ") == "nestlé"
    record = normalize_row(tmp_path, brand="TRADER JOE'S, N/A")
    assert record.brand == "TRADER JOE'S"
    assert record.brand_normalized == ["trader joe's"]
    assert record.source_values["brand"] == "TRADER JOE'S, N/A"


def test_category_placeholders_removed_without_guessing_hierarchy(tmp_path):
    tags = ["en:snacks", "en:null", "en:chocolate-biscuits", "en:undefined"]
    assert normalized_tags(tags, "Snacks, Chocolate Biscuits") == [
        "en:chocolate-biscuits",
        "en:snacks",
    ]
    record = normalize_row(tmp_path, category="en:null", categories_tags='["en:null"]')
    assert record.category == ""
    assert record.category_normalized == []
    assert record.source_values["category"] == "en:null"
    assert record.missing_value_reasons["category"] == "source_placeholder"
    assert normalized_tags([], "Snacks > Biscuits") == ["text:snacks > biscuits"]


def test_country_preserves_all_source_countries(tmp_path):
    record = normalize_row(tmp_path)
    assert record.country == "France, Spain, Belgium"
    assert record.country_normalized == ["en:belgium", "en:france", "en:spain"]
    assert record.countries_tags == ["en:belgium", "en:france", "en:spain"]


def test_missing_values_distinguish_absence_from_explicit_status(tmp_path):
    record = normalize_row(
        tmp_path,
        ingredients="",
        packaging="not applicable",
        quantity="unavailable",
        nutrition="null",
        category="undefined",
        categories_tags="[]",
    )
    assert record.ingredients == record.packaging == record.quantity == record.category == ""
    assert record.nutrition == {}
    assert record.missing_value_reasons["ingredients"] == "not_provided"
    assert record.missing_value_reasons["packaging"] == "source_not_applicable"
    assert record.missing_value_reasons["quantity"] == "source_unavailable"
    assert placeholder_reason("N/A") == "source_placeholder"
    assert record.data_quality_score == record.score(False)


def test_suspicious_nutrients_remain_source_facts_with_review_flag(tmp_path):
    raw = '{"carbohydrates_100g":147.0,"sugars_100g":0.0}'
    record = normalize_row(tmp_path, nutrition=raw, nutrition_basis="100g")
    assert record.nutrition == {"carbohydrates_100g": 147.0, "sugars_100g": 0.0}
    assert record.nutrition_review_required is True
    assert "nutrition:carbohydrates_100g:over_100g_per_100g" in record.normalization_issues
    assert "147" not in record.search_text


@pytest.mark.parametrize(
    "nutrition",
    [
        '{"sugars_100g":NaN}',
        '{"sugars_100g":-1}',
        '{"sugars_100g":true}',
        '{"sugars_100g":1,"sugars_100g":2}',
        "[]",
    ],
)
def test_invalid_nutrition_json_cannot_silently_pass(tmp_path, nutrition):
    with pytest.raises(ValueError):
        normalize_row(tmp_path, nutrition=nutrition)


@pytest.mark.parametrize(
    "format,expected",
    [("JPEG", "valid"), ("PNG", "valid"), ("WEBP", "valid"), ("GIF", "unsupported_format")],
)
def test_image_format_dimensions_size_and_readability(tmp_path, format, expected):
    path = tmp_path / "image.data"
    Image.new("RGB", (64, 80)).save(path, format=format)
    metadata = inspect_image(path.name, tmp_path)
    assert metadata["image_available"]
    assert metadata["image_format"] == format
    assert (metadata["image_width"], metadata["image_height"]) == (64, 80)
    assert metadata["image_size_bytes"] == path.stat().st_size
    assert metadata["image_validation_status"] == expected
    assert metadata["image_valid"] == (expected == "valid")


@pytest.mark.parametrize(
    "path,expected",
    [
        ("", "no_path"),
        ("missing.jpg", "missing_file"),
        ("../outside.jpg", "unsafe_path"),
        ("/absolute.jpg", "unsafe_path"),
        ("C:\\images\\x.jpg", "unsafe_path"),
        ("images/../x.jpg", "unsafe_path"),
        ("bad.jpg", "corrupt"),
    ],
)
def test_missing_corrupt_or_unsafe_images_never_marked_valid(tmp_path, path, expected):
    (tmp_path / "bad.jpg").write_bytes(b"not an image")
    metadata = inspect_image(path, tmp_path)
    assert metadata["image_validation_status"] == expected
    assert not metadata["image_valid"]
    record = normalize_row(tmp_path, image_path=path, image_status="downloaded")
    assert record.image_path == ""
    if path:
        assert record.source_values["image_path"] == path


def test_search_text_determinism_and_schema(tmp_path):
    first = normalize_row(tmp_path)
    second = normalize_row(tmp_path)
    assert first.model_dump() == second.model_dump()
    assert first.search_text == (
        "Product: Chocolate 70% Cocoa 2 x 50 g\nBrand: Test Brand\n"
        "Categories: en:chocolate-biscuits, en:snacks\nIngredients: Cocoa (70%), sugar, milk\n"
        "Countries: en:belgium, en:france, en:spain"
    )
    assert len(CanonicalProduct.model_fields) == 43
    assert {
        "source_values",
        "image_valid",
        "search_text",
        "brand_normalized",
    } <= first.model_dump().keys()
    with pytest.raises(ValueError, match="search text"):
        CanonicalProduct.model_validate({**first.model_dump(), "search_text": "invented answer"})


def test_full_pipeline_is_deterministic_read_only_on_inputs_and_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **k: pytest.fail("Unexpected network"))
    source = tmp_path / "input.csv"
    output = tmp_path / "canonical.csv"
    report_path = tmp_path / "quality.json"
    original_report = tmp_path / "off.json"
    Image.new("RGB", (100, 80)).save(tmp_path / "front.jpg")
    write_source(source, [source_row(image_path="front.jpg", image_status="downloaded")])
    original_report.write_text(
        json.dumps(
            {
                "product_master_sha256": digest(source),
                "source": {
                    "retrieved_at": "2026-09-16T12:00:00Z",
                    "source_url": "official-off-export",
                },
            }
        )
    )
    input_hashes = digest(source), digest(original_report)
    first = execute(source, output, report_path, original_report, tmp_path)
    output_bytes = output.read_bytes()
    second = execute(source, output, report_path, original_report, tmp_path)
    assert output.read_bytes() == output_bytes
    assert second["output_sha256"] == first["output_sha256"]
    assert (digest(source), digest(original_report)) == input_hashes
    assert second["ids_preserved_exactly"] and second["rows_removed"] == 0
    before_validate = report_path.read_bytes()
    assert (
        execute(source, output, report_path, original_report, tmp_path, validate=True)["status"]
        == "valid"
    )
    assert report_path.read_bytes() == before_validate
    # File replacement is detected by revalidation even if the replacement is a valid image.
    Image.new("RGB", (90, 80)).save(tmp_path / "front.jpg")
    with pytest.raises(ValueError, match="differs"):
        execute(source, output, report_path, original_report, tmp_path, validate=True)


def test_duplicate_rows_reported_not_removed(tmp_path):
    source = tmp_path / "input.csv"
    output = tmp_path / "out.csv"
    report = tmp_path / "audit.json"
    source_report = tmp_path / "no-source-report.json"
    write_source(source, [source_row(), source_row()])
    audit = execute(source, output, report, source_report, tmp_path, audit_only=True)
    assert audit["duplicate_product_ids"]["extra_rows"] == 1
    assert audit["duplicate_barcodes"]["extra_rows"] == 1
    with pytest.raises(ValueError, match="Duplicate"):
        execute(source, output, report, source_report, tmp_path)
    assert not output.exists()


def test_protected_input_and_source_report_cannot_be_overwritten(tmp_path):
    source = tmp_path / "input.csv"
    write_source(source, [source_row()])
    with pytest.raises(ValueError, match="separate"):
        execute(source, source, tmp_path / "report.json", tmp_path / "off.json", tmp_path)
    with pytest.raises(ValueError, match="separate"):
        execute(source, tmp_path / "out.csv", source, tmp_path / "off.json", tmp_path)


def test_source_report_checksum_and_output_tampering_rejected(tmp_path):
    source = tmp_path / "input.csv"
    write_source(source, [source_row()])
    off = tmp_path / "off.json"
    off.write_text('{"product_master_sha256":"bad"}')
    with pytest.raises(ValueError, match="does not describe"):
        execute(source, tmp_path / "out.csv", tmp_path / "quality.json", off, tmp_path)
    assert not (tmp_path / "out.csv").exists()


def test_unreadable_and_too_small_images_are_not_valid(tmp_path, monkeypatch):
    path = tmp_path / "small.jpg"
    Image.new("RGB", (10, 10)).save(path)
    assert inspect_image(path.name, tmp_path)["image_validation_status"] == "invalid_dimensions"
    original = Path.open

    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("test")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    assert inspect_image(path.name, tmp_path)["image_validation_status"] == "unreadable"


def test_invalid_url_is_removed_and_retained_in_source_values(tmp_path):
    record = normalize_row(tmp_path, image_url="http://127.0.0.1/private.jpg")
    assert record.image_url == ""
    assert "image:invalid_url" in record.normalization_issues
    assert record.source_values["image_url"] == "http://127.0.0.1/private.jpg"


@pytest.mark.parametrize("target", ["csv", "report"])
def test_validation_detects_tampering_with_data_or_quality_metrics(tmp_path, target):
    source, output = tmp_path / "input.csv", tmp_path / "canonical.csv"
    report, off = tmp_path / "quality.json", tmp_path / "off.json"
    write_source(source, [source_row()])
    execute(source, output, report, off, tmp_path)
    if target == "csv":
        output.write_bytes(output.read_bytes() + b"extra row")
    else:
        result = json.loads(report.read_text())
        result["images"]["valid"] = 999
        report.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="differs"):
        execute(source, output, report, off, tmp_path, validate=True)
