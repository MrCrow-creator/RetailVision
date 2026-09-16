import csv
import itertools
import json

from .config import Settings
from .models import Product
from .storage import digest, read_json


def validate_master(settings: Settings) -> dict:
    path = settings.data_dir / "processed" / "product_master.csv"
    report = read_json(settings.data_dir / "reports" / "openfoodfacts_quality.json")
    if digest(path) != report["product_master_sha256"]:
        raise ValueError("Product Master/report checksum mismatch")
    seen = set()
    images = 0
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            for field in (
                "nutrition",
                "categories_tags",
                "brands_tags",
                "countries_tags",
                "labels",
                "allergens",
            ):
                row[field] = json.loads(row[field])
            product = Product.model_validate(row)
            if product.product_id in seen:
                raise ValueError("Duplicate Product Master ID")
            seen.add(product.product_id)
            if product.image_status == "downloaded":
                image = (settings.data_dir / product.image_path).resolve()
                if not image.is_relative_to(settings.data_dir) or not image.is_file():
                    raise ValueError("Missing or invalid Product Master image path")
                state = read_json(image.with_suffix(".json"))
                if digest(image) != state["sha256"]:
                    raise ValueError("Image checksum mismatch")
                images += 1
    if len(seen) != report["final_product_count"] or images != report["image_downloaded_count"]:
        raise ValueError("Product Master/report counts disagree")
    return {
        "status": "valid",
        "unique_products": len(seen),
        "verified_local_images": images,
        "product_master_sha256": report["product_master_sha256"],
    }


def inspect_data(settings: Settings, kind: str, rows: int) -> None:
    if not 1 <= rows <= 20:
        raise ValueError("Inspect rows must be between 1 and 20")
    if kind == "validate":
        result = validate_master(settings)
    elif kind == "report":
        result = read_json(settings.data_dir / "reports" / "openfoodfacts_quality.json")
    elif kind == "master":
        with (settings.data_dir / "processed" / "product_master.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            result = list(itertools.islice(csv.DictReader(stream), rows))
    else:
        path = settings.data_dir / "raw" / "openfoodfacts" / settings.snapshot / "sample.jsonl"
        with path.open(encoding="utf-8") as stream:
            result = []
            for line in itertools.islice(stream, rows):
                raw = json.loads(line)
                fields = {
                    key: value
                    for key, value in raw.items()
                    if key in {"code", "schema_version", "images", "product_name"}
                    or key.startswith("nutrition")
                    or key == "nutriments"
                }
                result.append(fields)
    print(json.dumps(result, ensure_ascii=True, indent=2))
