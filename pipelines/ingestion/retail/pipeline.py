import hashlib
import json
from datetime import UTC, datetime, time
from pathlib import Path

from ..openfoodfacts.pipeline import single_run
from ..openfoodfacts.storage import atomic_bytes, digest, event, fingerprint
from . import RETAIL_VERSION
from .config import RetailSettings
from .data import encode_table, load_products, read_tables
from .generate import generate
from .rules import profile
from .schema import TABLES
from .validation import validate


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def build(products, checksum: str, settings: RetailSettings) -> tuple[dict[str, bytes], dict]:
    tables = generate(products, settings)
    result = validate(tables, products, settings)
    outputs = {f"{name}.csv": encode_table(name, rows) for name, rows in tables.items()}
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in outputs.items()}
    config = settings.model_dump(mode="json")
    metadata = {
        "dataset_kind": "controlled_synthetic_retail_operational_data",
        "description": (
            "Controlled synthetic retail operational data linked to real "
            "Open Food Facts product records."
        ),
        "pipeline_version": RETAIL_VERSION,
        "seed": settings.seed,
        "generation_timestamp": datetime.combine(
            settings.as_of_date, time(), tzinfo=UTC
        ).isoformat(),
        "timestamp_semantics": (
            "Declared simulation snapshot time; actual execution times are logged, not embedded."
        ),
        "as_of_date": settings.as_of_date.isoformat(),
        "configuration": config,
        "input_product_master_sha256": checksum,
        "product_count": len(products),
        "generation_id": fingerprint(
            {"input": checksum, "config": config, "version": RETAIL_VERSION}
        ),
        "files": hashes,
        "schemas": {f"{name}.csv": list(model.model_fields) for name, model in TABLES.items()},
        "limitations": [
            "Fictional stores, suppliers and operations; not actual retailer operations.",
            "Merchandising profiles and INR price bands are assumptions, "
            "not sourced market prices.",
            "General Grocery is shelf metadata; product categories remain unchanged.",
            "One shelf per product/store; shelf capacity is aggregate zone unit capacity.",
            "Sales are synthetic rolling-window aggregates; no stock-movement ledger is claimed.",
            "Only percentage discounts are modeled; no flat-discount or BOGO semantics.",
            "Six randomly selected placements anchor A-F; others use controlled variation.",
        ],
    }
    outputs["metadata.json"] = json_bytes(metadata)
    report = {
        **metadata,
        **result,
        "input_summary": {
            "products_missing_categories": sum(not p.category_normalized for p in products),
            "products_using_general_grocery_profile": sum(
                profile(p)[0] == "General Grocery" for p in products
            ),
            "products_with_nutrition_review_flags": sum(
                p.nutrition_review_required for p in products
            ),
            "nutrition_or_images_used_for_generation": False,
        },
        "metadata_sha256": hashlib.sha256(outputs["metadata.json"]).hexdigest(),
    }
    return outputs, report


def protect_paths(input_path, output_dir, report, source_report, data_dir):
    protected = {
        input_path.resolve(),
        (data_dir / "processed/product_master.csv").resolve(),
        (data_dir / "processed/product_master_canonical.csv").resolve(),
        (data_dir / "reports/openfoodfacts_quality.json").resolve(),
        (data_dir / "reports/product_master_canonical_quality.json").resolve(),
        (data_dir / "reports/product_master_audit.json").resolve(),
    }
    if source_report:
        protected.add(source_report.resolve())
    targets = [(output_dir / f"{name}.csv").resolve() for name in TABLES]
    targets += [(output_dir / "metadata.json").resolve(), report.resolve()]
    if len(targets) != len(set(targets)) or any(target in protected for target in targets):
        raise ValueError("Synthetic targets cannot overwrite inputs or each other")
    if report.suffix != ".json":
        raise ValueError("Quality report must use a .json path")
    for path in targets:
        if any(
            path.is_relative_to((data_dir / folder).resolve()) for folder in ("raw", "processed")
        ):
            raise ValueError(
                "Synthetic outputs cannot be written into real source data directories"
            )


def execute(
    input_path: Path,
    output_dir: Path,
    report_path: Path,
    settings: RetailSettings,
    data_dir: Path,
    *,
    source_report: Path | None = None,
    validate_only: bool = False,
    dry_run: bool = False,
) -> dict:
    protect_paths(input_path, output_dir, report_path, source_report, data_dir)
    products, checksum = load_products(input_path, source_report)
    settings.check_scale(len(products))
    if dry_run:
        return {
            "dry_run": True,
            "product_count": len(products),
            "input_sha256": checksum,
            "configuration": settings.model_dump(mode="json"),
            "output_directory": str(output_dir),
            "quality_report": str(report_path),
            "planned_tables": list(TABLES),
            "files_written": 0,
        }
    if validate_only:
        # Domain checks first provide actionable FK/constraint errors, independent of checksums.
        validate(read_tables(output_dir), products, settings)
        outputs, report = build(products, checksum, settings)
        for name, expected in outputs.items():
            if (output_dir / name).read_bytes() != expected:
                raise ValueError(
                    f"{name}: content differs from current input, seed, configuration or rules"
                )
        if report_path.read_bytes() != json_bytes(report):
            raise ValueError("Quality report differs from validated data/input/configuration")
        if digest(input_path) != checksum:
            raise ValueError("Product Master changed during validation")
        event("synthetic_retail_validated", generation_id=report["generation_id"])
        return {
            "status": "valid",
            "counts": report["counts"],
            "integrity": report["integrity"],
            "generation_id": report["generation_id"],
            "identical_files_verified": len(outputs) + 1,
            "verified_output_set_sha256": fingerprint(
                {
                    **{
                        name: hashlib.sha256(content).hexdigest()
                        for name, content in outputs.items()
                    },
                    "quality_report": hashlib.sha256(json_bytes(report)).hexdigest(),
                }
            ),
        }
    with single_run(data_dir):
        outputs, report = build(products, checksum, settings)
        if digest(input_path) != checksum:
            raise ValueError("Product Master changed during generation; outputs not published")
        for name, content in outputs.items():
            atomic_bytes(output_dir / name, content)
        # Publish manifest/report last. Validation detects interrupted or mixed output sets.
        atomic_bytes(report_path, json_bytes(report))
    event("synthetic_retail_generated", generation_id=report["generation_id"], **report["counts"])
    return report
