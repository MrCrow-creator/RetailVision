import csv
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..canonicalization.schema import CanonicalProduct
from ..canonicalization.transform import unique_object
from ..openfoodfacts.storage import digest, read_json
from .schema import KEYS, TABLES

JSON_FIELDS = (
    "nutrition",
    "categories_tags",
    "brands_tags",
    "countries_tags",
    "labels",
    "allergens",
    "source_values",
    "brand_normalized",
    "category_normalized",
    "country_normalized",
    "missing_value_reasons",
    "normalization_issues",
)


def load_products(path: Path, source_report: Path | None = None):
    checksum = digest(path)
    products, ids, barcodes = [], set(), set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(CanonicalProduct.model_fields):
            raise ValueError("Expected the canonical 43-column Product Master schema")
        for index, row in enumerate(reader, 2):
            if None in row or None in row.values():
                raise ValueError(f"Malformed Product Master CSV record {index}")
            if row["product_id"] != "OFF_" + row["barcode"]:
                raise ValueError(f"Product Master identity mismatch in record {index}")
            if row["product_id"] in ids or row["barcode"] in barcodes:
                raise ValueError(f"Duplicate Product Master identity: {row['product_id']}")
            ids.add(row["product_id"])
            barcodes.add(row["barcode"])
            for field in JSON_FIELDS:
                row[field] = json.loads(row[field], object_pairs_hook=unique_object)
            for field in ("image_width", "image_height", "image_size_bytes"):
                if row[field] == "":
                    row[field] = None
            product = CanonicalProduct.model_validate(row)
            products.append(product)
    if not products:
        raise ValueError("Product Master is empty; products will not be fabricated")
    if digest(path) != checksum:
        raise ValueError("Product Master changed during loading")
    if source_report is not None:
        source = read_json(source_report)
        if source.get("output_sha256") != checksum or source.get("row_count") != len(products):
            raise ValueError("Canonical report/input checksum or row count mismatch")
    return sorted(products, key=lambda p: p.product_id), checksum


def encode_table(name: str, rows: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(TABLES[name].model_fields), lineterminator="\n")
    writer.writeheader()
    for row in sorted(rows, key=lambda r: tuple(r[field] for field in KEYS[name])):
        writer.writerow(
            {
                key: format(value, ".2f")
                if isinstance(value, Decimal)
                else value.isoformat()
                if isinstance(value, date)
                else value
                for key, value in row.items()
            }
        )
    return stream.getvalue().encode("utf-8")


def read_tables(directory: Path) -> dict:
    tables = {}
    for name, schema in TABLES.items():
        with (directory / f"{name}.csv").open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(schema.model_fields):
                raise ValueError(f"Invalid columns in {name}.csv")
            tables[name] = list(reader)
            if any(None in row or None in row.values() for row in tables[name]):
                raise ValueError(f"Malformed row in {name}.csv")
    return tables
