import copy
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from ingestion.canonicalization.images import inspect_image
from ingestion.canonicalization.pipeline import encode
from ingestion.canonicalization.transform import cell, transform
from ingestion.openfoodfacts.models import normalize
from ingestion.openfoodfacts.storage import digest
from ingestion.retail.config import RetailSettings
from ingestion.retail.data import load_products
from ingestion.retail.generate import generate
from ingestion.retail.pipeline import build, execute, json_bytes
from ingestion.retail.rules import current_price, profile, promoted_days
from ingestion.retail.schema import TABLES, Promotion
from ingestion.retail.validation import RetailValidationError, validate


@pytest.fixture
def products(tmp_path):
    catalog = []
    for index in range(60):
        tags = ["en:beverages"] if index % 3 == 0 else ["en:snacks"] if index % 3 == 1 else []
        product, errors = normalize(
            {
                "code": str(8901234567890 + index),
                "product_name": f"Fixture product {index}",
                "brands": "Fixture brand",
                "categories_tags": tags,
            }
        )
        assert not errors
        row = {key: cell(value) for key, value in product.model_dump().items()}
        catalog.append(transform(row, inspect_image("", tmp_path)))
    return catalog


@pytest.fixture
def settings():
    return RetailSettings(
        _env_file=None,
        seed=42,
        store_count=4,
        shelves_per_store=4,
        supplier_count=6,
        promotion_count=10,
        placement_count=120,
    )


@pytest.fixture
def tables(products, settings):
    return generate(products, settings)


def test_reference_coverage_distribution_and_scenarios(products, settings, tables):
    result = validate(tables, products, settings)
    ids = {p.product_id for p in products}
    assert result["integrity"]["valid"]
    assert {p["product_id"] for p in tables["placements"]} == ids
    assert {p["product_id"] for p in tables["product_suppliers"]} == ids
    assert len(tables["product_suppliers"]) == len(products)
    assert len(tables["placements"]) == settings.placement_count
    assert (
        len({(p["product_id"], p["store_id"]) for p in tables["placements"]})
        == settings.placement_count
    )
    assert all(details["count"] > 0 for details in result["inventory_distribution"].values())
    assert all(count > 0 for count in result["scenario_counts"].values())
    assert (
        result["scenario_counts"]["E"]
        < result["promotion_distribution"]["active_promoted_placements"]
    )
    assert result["scenario_counts"]["A"] < result["low_stock_count"]
    assert result["sales_distribution"]["low_sales_product_store_count"] > 0
    assert result["sales_distribution"]["high_sales_product_store_count"] > 0
    assert 0.4 < result["inventory_distribution"]["healthy"]["percentage"] / 100 < 0.9
    assert all(
        i["stock"] <= i["max_stock"] and i["reorder_level"] < i["max_stock"]
        for i in tables["inventory"]
    )
    assert all(s["units_sold_7d"] <= s["units_sold_30d"] for s in tables["sales"])


@pytest.mark.parametrize(
    "table,field,kind",
    [
        ("shelves", "store_id", "store"),
        ("placements", "product_id", "product"),
        ("placements", "store_id", "store"),
        ("placements", "shelf_id", "shelf"),
        ("inventory", "placement_id", "placement"),
        ("inventory", "product_id", "product"),
        ("inventory", "shelf_id", "shelf"),
        ("inventory", "store_id", "store"),
        ("sales", "product_id", "product"),
        ("sales", "store_id", "store"),
        ("prices", "product_id", "product"),
        ("prices", "store_id", "store"),
        ("product_suppliers", "product_id", "product"),
        ("product_suppliers", "supplier_id", "supplier"),
        ("product_promotions", "product_id", "product"),
        ("product_promotions", "promotion_id", "promotion"),
        ("product_promotions", "placement_id", "placement"),
        ("product_promotions", "shelf_id", "shelf"),
    ],
)
def test_invalid_foreign_keys_fail_without_removing_rows(
    products, settings, tables, table, field, kind
):
    tables[table][0][field] = "DOES_NOT_EXIST"
    original_length = len(tables[table])
    with pytest.raises(RetailValidationError) as caught:
        validate(tables, products, settings)
    assert caught.value.result[f"invalid_{kind}_references"] > 0
    assert len(tables[table]) == original_length
    assert tables[table][0][field] == "DOES_NOT_EXIST"


def test_known_shelf_in_wrong_store_and_inventory_wrong_placement(products, settings, tables):
    placement = tables["placements"][0]
    other = next(s for s in tables["shelves"] if s["store_id"] != placement["store_id"])
    placement["shelf_id"] = other["shelf_id"]
    with pytest.raises(RetailValidationError) as caught:
        validate(tables, products, settings)
    codes = {e["code"] for e in caught.value.result["errors"]}
    assert "shelf_store_mismatch" in codes
    assert "placement_mismatch" in codes


@pytest.mark.parametrize("table", list(TABLES))
def test_duplicate_primary_keys_are_rejected(products, settings, tables, table):
    tables[table].append(copy.deepcopy(tables[table][0]))
    with pytest.raises(RetailValidationError) as caught:
        validate(tables, products, settings)
    assert any(e["code"] == "duplicate_key" for e in caught.value.result["errors"])


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("inventory", "stock", -1),
        ("inventory", "stock", 99999),
        ("inventory", "reorder_level", 99999),
        ("inventory", "max_stock", 0),
        ("sales", "units_sold_7d", 99999),
        ("sales", "units_sold_30d", -1),
        ("promotions", "discount_percentage", 0),
        ("promotions", "discount_percentage", 99),
        ("placements", "facings", 0),
        ("prices", "currency", "USD"),
        ("prices", "base_price", "25000.00"),
        ("prices", "current_price", "0.01"),
        ("shelves", "capacity", 1),
    ],
)
def test_constraints_and_price_rules_are_enforced(products, settings, tables, table, field, value):
    tables[table][0][field] = value
    with pytest.raises(RetailValidationError):
        validate(tables, products, settings)


@pytest.mark.parametrize("offset", [0, -1])
def test_invalid_promotion_dates_fail(products, settings, tables, offset):
    tables["promotions"][0]["end_date"] = tables["promotions"][0]["start_date"] + timedelta(
        days=offset
    )
    with pytest.raises(RetailValidationError):
        validate(tables, products, settings)


def test_missing_inventory_supplier_and_sales_coverage_fail(products, settings, tables):
    for table in ("inventory", "product_suppliers", "sales"):
        tables[table].pop()
    with pytest.raises(RetailValidationError) as caught:
        validate(tables, products, settings)
    codes = {e["code"] for e in caught.value.result["errors"]}
    assert {"inventory_coverage", "supplier_coverage", "placement_coverage"} <= codes


def test_facing_intervals_may_not_overlap(products, settings, tables):
    first = tables["placements"][0]
    second = next(p for p in tables["placements"][1:] if p["shelf_id"] == first["shelf_id"])
    second["shelf_position"] = first["shelf_position"]
    with pytest.raises(RetailValidationError) as caught:
        validate(tables, products, settings)
    assert any(e["code"] == "overlapping_facings" for e in caught.value.result["errors"])


def test_promotion_math_and_sales_window_overlap():
    promo = Promotion(
        promotion_id="PROMO_001",
        promotion_name="Fixture",
        promotion_type="SEASONAL",
        discount_percentage=15,
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 20),
    )
    assert current_price(Decimal("99.50"), promo, date(2026, 9, 17)) == Decimal("84.58")
    assert current_price(Decimal("99.50"), promo, date(2026, 9, 21)) == Decimal("99.50")
    assert promoted_days(promo, date(2026, 9, 14), date(2026, 9, 20)) == 7
    assert promoted_days(promo, date(2026, 9, 21), date(2026, 9, 27)) == 0


def test_all_outputs_are_deterministic_and_categories_not_modified(products, settings):
    before = [p.model_dump() for p in products]
    files1, report1 = build(products, "fixture-checksum", settings)
    files2, report2 = build(list(reversed(products)), "fixture-checksum", settings)
    assert files1 == files2
    assert json_bytes(report1) == json_bytes(report2)
    assert [p.model_dump() for p in products] == before
    missing = next(p for p in products if not p.category_normalized)
    assert profile(missing)[0] == "General Grocery"
    assert missing.category == ""
    changed, _ = build(products, "fixture-checksum", settings.model_copy(update={"seed": 43}))
    assert changed["inventory.csv"] != files1["inventory.csv"]


def test_dry_run_no_writes_then_generation_and_read_only_validation(
    products, settings, tmp_path, monkeypatch
):
    source = tmp_path / "canonical.csv"
    source.write_bytes(encode(products))
    original = source.read_bytes()
    out, report, root = tmp_path / "out", tmp_path / "quality.json", tmp_path / "data"
    monkeypatch.setattr(
        httpx.Client, "request", lambda *a, **k: pytest.fail("No network permitted")
    )
    result = execute(source, out, report, settings, root, dry_run=True)
    assert result["files_written"] == 0
    assert not out.exists() and not root.exists() and not report.exists()
    execute(source, out, report, settings, root)
    first = {
        name: (out / name).read_bytes() for name in [*(f"{t}.csv" for t in TABLES), "metadata.json"]
    }
    first_report = report.read_bytes()
    assert (
        execute(source, out, report, settings, root, validate_only=True)["identical_files_verified"]
        == 12
    )
    assert report.read_bytes() == first_report
    execute(source, out, report, settings, root)
    assert report.read_bytes() == first_report
    assert all((out / name).read_bytes() == content for name, content in first.items())
    assert source.read_bytes() == original
    # Same records, different source-file bytes: provenance must still detect the new input version.
    source.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="metadata.json"):
        execute(source, out, report, settings, root, validate_only=True)


def test_tampered_report_or_metadata_cannot_be_accepted(products, settings, tmp_path):
    source, out, report = tmp_path / "input.csv", tmp_path / "out", tmp_path / "report.json"
    source.write_bytes(encode(products))
    execute(source, out, report, settings, tmp_path)
    metadata = json.loads((out / "metadata.json").read_text())
    metadata["seed"] = 1
    (out / "metadata.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="metadata.json"):
        execute(source, out, report, settings, tmp_path, validate_only=True)
    execute(source, out, report, settings, tmp_path)
    quality = json.loads(report.read_text())
    quality["counts"]["stores"] = 999
    report.write_text(json.dumps(quality))
    with pytest.raises(ValueError, match="Quality report"):
        execute(source, out, report, settings, tmp_path, validate_only=True)


def test_input_duplicates_and_empty_catalog_fail(products, tmp_path):
    source = tmp_path / "input.csv"
    source.write_bytes(encode([products[0], products[0]]))
    with pytest.raises(ValueError, match="Duplicate"):
        load_products(source)
    source.write_bytes(encode([]))
    with pytest.raises(ValueError, match="empty"):
        load_products(source)


def test_input_report_binding_output_protection_and_infeasible_scale(products, settings, tmp_path):
    source, report = tmp_path / "input.csv", tmp_path / "canonical_report.json"
    source.write_bytes(encode(products))
    report.write_text('{"output_sha256":"mismatch","row_count":60}')
    with pytest.raises(ValueError, match="checksum"):
        load_products(source, report)
    with pytest.raises(ValueError, match="overwrite"):
        execute(source, tmp_path, tmp_path / "metadata.json", settings, tmp_path)
    with pytest.raises(ValueError, match="source data"):
        execute(source, tmp_path / "processed", tmp_path / "report.json", settings, tmp_path)
    with pytest.raises(ValueError, match="Placement count"):
        settings.check_scale(1)


def test_cli_determinism_across_process_hash_seeds(products, tmp_path):
    source = tmp_path / "input.csv"
    source.write_bytes(encode(products))
    original_hash = digest(source)
    reports, snapshots = [], []
    for index, hash_seed in enumerate(("1", "999")):
        directory = tmp_path / f"run-{index}"
        report = tmp_path / f"report-{index}.json"
        command = [
            sys.executable,
            "-m",
            "ingestion.retail",
            "--input",
            str(source),
            "--output-dir",
            str(directory),
            "--report",
            str(report),
            "--data-dir",
            str(tmp_path),
            "--seed",
            "42",
            "--store-count",
            "4",
            "--shelves-per-store",
            "4",
            "--supplier-count",
            "6",
            "--promotion-count",
            "10",
            "--placement-count",
            "120",
        ]
        process = subprocess.run(
            command,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        reports.append(report.read_bytes())
        snapshots.append(
            {
                name: (directory / name).read_bytes()
                for name in [*(f"{t}.csv" for t in TABLES), "metadata.json"]
            }
        )
    assert snapshots[0] == snapshots[1]
    assert reports[0] == reports[1]
    assert digest(source) == original_hash
