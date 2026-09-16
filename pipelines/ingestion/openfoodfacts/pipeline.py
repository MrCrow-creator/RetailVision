import csv
import gzip
import io
import itertools
import json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import httpx

from . import PIPELINE_VERSION
from .config import Settings
from .images import ImageDownloader
from .models import Product, normalize, preference
from .source import records, snapshot
from .storage import (
    atomic_bytes,
    atomic_json,
    canonical,
    digest,
    event,
    fingerprint,
    now,
    read_json,
)


def normalize_sample(
    path: Path,
    source_format: str = "jsonl",
    max_records: int | None = None,
) -> tuple[list[Product], dict]:
    counts = Counter(
        raw_records=0,
        invalid_records=0,
        valid_records=0,
        invalid_barcode=0,
        missing_product_name=0,
        malformed_record=0,
        duplicates_removed=0,
    )
    products = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as stream:
        for raw in itertools.islice(records(stream, source_format), max_records):
            counts["raw_records"] += 1
            product, errors = normalize(raw)
            if errors:
                counts["invalid_records"] += 1
                counts.update(errors)
                continue
            counts["valid_records"] += 1
            previous = products.get(product.barcode)
            if previous:
                counts["duplicates_removed"] += 1
            if previous is None or preference(product) < preference(previous):
                products[product.barcode] = product
    counts["valid_unique_records"] = len(products)
    return sorted(products.values(), key=lambda p: (preference(p), p.barcode)), dict(counts)


def export_csv(products: list[Product]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(Product.model_fields), lineterminator="\n")
    writer.writeheader()
    seen = set()
    for product in sorted(products, key=lambda p: p.product_id):
        record = Product.model_validate(product.model_dump()).model_dump()
        if product.product_id in seen:
            raise ValueError("Duplicate canonical product ID in final output")
        seen.add(product.product_id)
        writer.writerow(
            {
                key: canonical(value) if isinstance(value, (dict, list)) else value
                for key, value in record.items()
            }
        )
    return stream.getvalue().encode("utf-8")


def run(settings: Settings, *, dry_run: bool = False, retry_failed: bool = False) -> dict:
    event("ingestion_started", target=settings.target_products, dry_run=dry_run)
    with httpx.Client(
        headers={"User-Agent": settings.user_agent},
        timeout=settings.image_timeout,
        limits=httpx.Limits(max_connections=settings.image_workers),
    ) as client:
        sample, metadata = snapshot(settings, client, dry_run)
        raw_hash = digest(sample)
        key = fingerprint({"raw": raw_hash, "version": PIPELINE_VERSION})
        cache = settings.data_dir / "processed" / "openfoodfacts" / f"{key}.json"
        if cache.exists() and not metadata.get("dry_local"):
            saved = read_json(cache)
            candidates = [Product.model_validate(record) for record in saved["products"]]
            counts = saved["counts"]
            event("normalization_reused", products=len(candidates))
        else:
            source_format = settings.source_format if metadata.get("dry_local") else "jsonl"
            candidates, counts = normalize_sample(sample, source_format, settings.max_raw_records)
            if not dry_run:
                atomic_json(
                    cache, {"products": [p.model_dump() for p in candidates], "counts": counts}
                )
        selected = candidates[: settings.target_products]
        image_stats = {}
        if not dry_run:
            image_stats = ImageDownloader(settings, client, retry_failed).run(selected)
        else:
            for product in selected:
                product.image_status = "not_checked" if product.image_url else "missing"
                product.data_quality_score = product.score(False)
        report = {
            "pipeline_version": PIPELINE_VERSION,
            "generated_at": now(),
            "dry_run": dry_run,
            "source": metadata,
            "raw_sha256": raw_hash,
            "configuration": settings.model_dump(mode="json", exclude={"user_agent"}),
            **counts,
            "final_product_count": len(selected),
            "target_reached": len(selected) == settings.target_products,
            "image_available_count": sum(bool(p.image_url) for p in selected),
            "image_downloaded_count": sum(p.image_status == "downloaded" for p in selected),
            "image_failure_count": sum(p.image_status == "failed" for p in selected),
            "image_missing_url_count": sum(not p.image_url for p in selected),
            "image_not_checked_count": sum(p.image_status == "not_checked" for p in selected),
            "barcode_checksum_failure_count": sum(not p.barcode_checksum_valid for p in selected),
            "average_data_quality_score": round(
                sum(p.data_quality_score for p in selected) / len(selected), 4
            )
            if selected
            else 0,
            **{
                f"missing_{field}_count": sum(not getattr(p, field) for p in selected)
                for field in (
                    "brand",
                    "category",
                    "ingredients",
                    "nutrition",
                    "country",
                    "packaging",
                )
            },
            "image_run": image_stats,
            "limitations": [
                "Bounded export sample; not random or representative of all retail products.",
                "Presence score measures completeness, not verified factual accuracy.",
                "Barcode validity is OFF structural validity; GS1 checksum is reported separately.",
                "AWS image mirror is periodic; some current front images may be absent.",
            ],
        }
        if not dry_run:
            output = settings.data_dir / "processed" / "product_master.csv"
            atomic_bytes(output, export_csv(selected))
            report["product_master_sha256"] = digest(output)
            report["product_master_path"] = str(output)
            atomic_bytes(
                settings.data_dir / "reports" / "openfoodfacts_quality.json",
                (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
        event(
            "ingestion_finished",
            **counts,
            final_products=len(selected),
            images_downloaded=report["image_downloaded_count"],
            images_failed=report["image_failure_count"],
            average_quality=report["average_data_quality_score"],
        )
        return report


@contextmanager
def single_run(data_dir: Path):
    """OS releases the lock after a crash; no stale PID lock to clear manually."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".ingestion.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        import sys

        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError("Another ingestion is running for this data directory") from None
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError("Another ingestion is running for this data directory") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
