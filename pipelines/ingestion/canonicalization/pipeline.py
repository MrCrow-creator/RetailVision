import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

from ..openfoodfacts.models import Product
from ..openfoodfacts.storage import atomic_bytes, digest, now, read_json
from . import CANONICAL_VERSION
from .audit import audit_rows, image_summary, missing_counts
from .images import inspect_image
from .schema import CanonicalProduct
from .transform import cell, transform


def read_input(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)) or set(columns) != set(Product.model_fields):
            raise ValueError("Input must contain exactly the 25 Milestone 2 Product columns")
        rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("Empty dataset or malformed CSV row; no products will be discarded")
    return rows, columns


def encode(products: list[CanonicalProduct]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=list(CanonicalProduct.model_fields), lineterminator="\n"
    )
    writer.writeheader()
    for product in sorted(products, key=lambda p: p.product_id):
        writer.writerow({key: cell(value) for key, value in product.model_dump().items()})
    return stream.getvalue().encode("utf-8")


def build(input_path: Path, data_dir: Path) -> tuple[bytes, dict]:
    before_hash = digest(input_path)
    rows, columns = read_input(input_path)
    images = [inspect_image(row["image_path"], data_dir) for row in rows]
    audit = audit_rows(rows, columns, images)
    if (
        audit["duplicate_product_ids"]["extra_rows"]
        or audit["duplicate_barcodes"]["extra_rows"]
        or audit["identity_mismatches"]
        or audit["duplicate_rows"]
    ):
        raise ValueError("Duplicate or mismatched identities: use --audit; no rows were removed")
    products = [transform(row, image) for row, image in zip(rows, images, strict=True)]
    if [(p.product_id, p.barcode) for p in products] != [
        (r["product_id"], r["barcode"]) for r in rows
    ]:
        raise ValueError("Identity changed during transformation")
    if digest(input_path) != before_hash:
        raise ValueError("Input changed during processing; output not published")
    content = encode(products)
    cleaned = [{key: cell(value) for key, value in p.model_dump().items()} for p in products]
    issues = Counter(issue for p in products for issue in p.normalization_issues)
    report = {
        "pipeline_version": CANONICAL_VERSION,
        "processed_at": now(),
        "source_dataset": str(input_path.resolve()),
        "image_root": str(data_dir.resolve()),
        "input_sha256": before_hash,
        "output_sha256": hashlib.sha256(content).hexdigest(),
        "input_audit": audit,
        "row_count": len(products),
        "column_count": len(CanonicalProduct.model_fields),
        "columns": list(CanonicalProduct.model_fields),
        "rows_removed": 0,
        "ids_preserved_exactly": True,
        "barcodes_preserved_exactly": True,
        "missing_values": missing_counts(cleaned),
        "images": image_summary(images),
        "valid_search_text_products": sum(bool(p.search_text.strip()) for p in products),
        "nutrition_review_products": sum(p.nutrition_review_required for p in products),
        "normalization_issue_counts": dict(sorted(issues.items())),
        "changed_fields": dict(
            sorted(Counter(field for p in products for field in p.source_values).items())
        ),
        "completeness": {
            "before": round(sum(float(row["data_quality_score"]) for row in rows) / len(rows), 4),
            "after": round(sum(p.data_quality_score for p in products) / len(products), 4),
            "formula": (
                "sum(barcode, name, brand, category, verified_image, ingredients, nutrition) / 7"
            ),
            "meaning": "Completeness, not accuracy. Source placeholders earn no presence credit.",
        },
        "image_failures": [
            {
                "product_id": row["product_id"],
                "path": row["image_path"],
                "status": image["image_validation_status"],
            }
            for row, image in zip(rows, images, strict=True)
            if image["image_validation_status"] not in {"valid", "no_path"}
        ],
        "review_required_products": [
            {"product_id": p.product_id, "issues": p.normalization_issues}
            for p in products
            if p.normalization_issues
        ],
    }
    return content, report


def protect_paths(
    input_path: Path, output: Path, report: Path, source_report: Path, data_dir: Path
):
    protected = {
        input_path.resolve(),
        source_report.resolve(),
        (data_dir / "processed/product_master.csv").resolve(),
        (data_dir / "reports/openfoodfacts_quality.json").resolve(),
    }
    targets = [output.resolve(), report.resolve()]
    if targets[0] == targets[1] or any(path in protected for path in targets):
        raise ValueError("Output/report must be separate from each other and Milestone 2 inputs")
    if any(path.is_relative_to((data_dir / "raw").resolve()) for path in targets):
        raise ValueError("Canonical outputs cannot overwrite raw data or images")
    if output.suffix != ".csv" or report.suffix != ".json":
        raise ValueError("Expected .csv output and .json report")


def provenance(source_report: Path, input_sha: str) -> dict:
    if not source_report.exists():
        return {"source_retrieval_date": None, "source_report_status": "not_provided"}
    original = read_json(source_report)
    if original.get("product_master_sha256") != input_sha:
        raise ValueError(
            "Source report does not describe the input CSV; provide its matching report"
        )
    return {
        "source_retrieval_date": original["source"].get("retrieved_at"),
        "source_url": original["source"].get("source_url"),
        "source_report": str(source_report.resolve()),
        "source_report_sha256": digest(source_report),
        "source_report_status": "checksum_verified",
    }


def execute(
    input_path: Path,
    output: Path,
    report_path: Path,
    source_report: Path,
    data_dir: Path,
    *,
    validate: bool = False,
    audit_only: bool = False,
) -> dict:
    protect_paths(input_path, output, report_path, source_report, data_dir)
    if audit_only:
        rows, columns = read_input(input_path)
        report = audit_rows(
            rows, columns, [inspect_image(row["image_path"], data_dir) for row in rows]
        )
        report.update(
            input_sha256=digest(input_path),
            processed_at=now(),
            pipeline_version=CANONICAL_VERSION,
            source_dataset=str(input_path.resolve()),
        )
    else:
        content, report = build(input_path, data_dir)
        report.update(provenance(source_report, report["input_sha256"]))
        report["output_dataset"] = str(output.resolve())
        if validate:
            existing = read_json(report_path)
            # Processing time is informational. Every other report field must reproduce exactly.
            expected = {key: value for key, value in report.items() if key != "processed_at"}
            recorded = {key: value for key, value in existing.items() if key != "processed_at"}
            if recorded != expected or output.read_bytes() != content:
                raise ValueError(
                    "Canonical data/report differs from current input, rules or images"
                )
            return {
                "status": "valid",
                "rows": report["row_count"],
                "images": report["images"]["valid"],
                "output_sha256": report["output_sha256"],
            }
        atomic_bytes(output, content)
    atomic_bytes(
        report_path, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    return report
