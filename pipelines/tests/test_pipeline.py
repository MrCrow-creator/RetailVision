import csv
import io
import json

import httpx
import pytest
from PIL import Image

from ingestion.openfoodfacts.config import Settings
from ingestion.openfoodfacts.images import ImageDownloader
from ingestion.openfoodfacts.inspection import validate_master
from ingestion.openfoodfacts.models import normalize
from ingestion.openfoodfacts.network import RateLimiter
from ingestion.openfoodfacts.pipeline import run


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(RateLimiter, "wait", lambda self: None)


def picture():
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color="red").save(buffer, format="JPEG")
    return buffer.getvalue()


def product(code="8901234567890"):
    return normalize(
        {
            "code": code,
            "product_name": "Test product",
            "images": {"selected": {"front": {"en": {"imgid": 2}}}},
        }
    )[0]


def test_image_failure_does_not_abort_and_success_is_not_redownloaded(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "/890/" in request.url.path:
            return httpx.Response(200, content=picture(), headers={"content-type": "image/jpeg"})
        return httpx.Response(404)

    settings = Settings(_env_file=None, data_dir=tmp_path, max_retries=0)
    products = [product(), product("0034000470693")]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        downloader = ImageDownloader(settings, client)
        first = downloader.run(products)
        assert first["downloaded_this_run"] == 1
        assert first["failed_this_run"] == 1
        assert products[0].image_status == "downloaded"
        assert (settings.data_dir / products[0].image_path).is_file()
        assert products[1].image_status == "failed"
        assert downloader.run(products)["cached_images"] == 2
        assert len(calls) == 2
        ImageDownloader(settings, client, retry_failed=True).run(products)
        assert len(calls) == 3  # Only the failed image is retried.


@pytest.mark.parametrize("failure", ["corrupt", "timeout", "unsupported", "oversize"])
def test_bad_image_is_reported_without_crashing(tmp_path, failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("test timeout")
        content = b"bad" if failure == "corrupt" else picture()
        if failure == "oversize":
            content = b"x" * 2048
        mime = "text/html" if failure == "unsupported" else "image/jpeg"
        return httpx.Response(200, content=content, headers={"content-type": mime})

    settings = Settings(_env_file=None, data_dir=tmp_path, max_retries=0, max_image_bytes=1024)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        products = [product()]
        assert ImageDownloader(settings, client).run(products)["failed_this_run"] == 1
        assert products[0].image_path == ""
        assert products[0].data_quality_score == round(2 / 7, 4)


def test_corrupted_cached_image_is_recovered(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=picture(), headers={"content-type": "image/jpeg"})

    settings = Settings(_env_file=None, data_dir=tmp_path)
    products = [product()]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        downloader = ImageDownloader(settings, client)
        downloader.run(products)
        (settings.data_dir / products[0].image_path).write_bytes(b"corrupted")
        downloader.run(products)
    assert len(calls) == 2
    assert (settings.data_dir / products[0].image_path).read_bytes() == picture()


def test_pipeline_report_csv_resume_and_shortfall(tmp_path, monkeypatch):
    raw = tmp_path / "source.jsonl"
    rows = [
        {"code": "0034000470693", "product_name": "Test, item", "brands": "Test brand"},
        {"code": "034000470693", "product_name": "Test"},
        {"code": "8901234567890", "product_name": "Other"},
        {"code": "invalid", "product_name": "Rejected"},
        {"code": "12345678", "product_name": ""},
    ]
    raw.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        source_file=str(raw),
        target_products=3,
        max_raw_records=10,
        download_images=False,
    )
    report = run(settings)
    assert report["raw_records"] == 5
    assert report["valid_records"] == 3
    assert report["invalid_records"] == 2
    assert report["duplicates_removed"] == 1
    assert report["final_product_count"] == 2
    assert report["target_reached"] is False
    master = settings.data_dir / "processed" / "product_master.csv"
    content = master.read_bytes()
    with master.open(encoding="utf-8", newline="") as stream:
        products = list(csv.DictReader(stream))
    assert products[0]["product_id"] == "OFF_0034000470693"
    assert products[0]["barcode"] == "0034000470693"
    assert len({p["product_id"] for p in products}) == 2
    monkeypatch.setattr(
        "ingestion.openfoodfacts.pipeline.normalize_sample",
        lambda *a: pytest.fail("Completed normalization should be reused"),
    )
    resumed = run(settings)
    assert master.read_bytes() == content
    assert resumed["product_master_sha256"] == report["product_master_sha256"]
    assert (settings.data_dir / "reports" / "openfoodfacts_quality.json").is_file()
    assert validate_master(settings)["unique_products"] == 2
    master.write_bytes(content + b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        validate_master(settings)


def test_dry_run_is_local_bounded_and_read_only(tmp_path):
    raw = tmp_path / "local.jsonl"
    raw.write_text(
        "\n".join(
            json.dumps({"code": str(8901234567890 + n), "product_name": "Test"}) for n in range(5)
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        source_file=str(raw),
        target_products=1,
        max_raw_records=2,
    )
    report = run(settings, dry_run=True)
    assert report["raw_records"] == 2
    assert not settings.data_dir.exists()
