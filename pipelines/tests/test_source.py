import gzip
import io
import json

import httpx
import pytest

from ingestion.openfoodfacts.config import Settings
from ingestion.openfoodfacts.network import FetchError, RateLimiter, fetch_bytes, retry_delay
from ingestion.openfoodfacts.source import RangeReader, records, snapshot


def test_malformed_json_and_nonfinite_numbers_are_reportable_rows():
    source = io.StringIO('{"nutriments":NaN}\nnot json\n{"code":"12345678"}\n')
    assert list(records(source, "jsonl")) == [None, None, {"code": "12345678"}]


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(RateLimiter, "wait", lambda self: None)


def test_raw_chunks_resume_without_network_and_detect_corruption(tmp_path):
    payload = gzip.compress(b'{"code":"8901234567890","product_name":"Test"}\n')
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            206,
            content=payload,
            headers={
                "content-range": f"bytes 0-{len(payload) - 1}/{len(payload)}",
                "etag": '"v1"',
            },
        )

    settings = Settings(_env_file=None, data_dir=tmp_path, target_products=1, max_raw_records=1)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = RangeReader(tmp_path, settings, client)
        assert gzip.decompress(io.BufferedReader(first).read()) == gzip.decompress(payload)
        assert len(requests) == 1
        second = RangeReader(tmp_path, settings, client)
        assert gzip.decompress(io.BufferedReader(second).read()) == gzip.decompress(payload)
        assert len(requests) == 1
        saved = tmp_path / "chunks" / "000000.json"
        content = json.loads(saved.read_text())
        content["sha256"] = "bad"
        saved.write_text(json.dumps(content))
        with pytest.raises(FetchError, match="checksum"):
            RangeReader(tmp_path, settings, client).chunk(0)


def test_changed_export_cannot_mix_cached_and_new_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr("ingestion.openfoodfacts.source.CHUNK_SIZE", 10)
    calls = 0

    def handler(request):
        nonlocal calls
        start = calls * 10
        calls += 1
        return httpx.Response(
            206,
            content=b"0123456789",
            headers={
                "content-range": f"bytes {start}-{start + 9}/30",
                "etag": f'"v{calls}"',
            },
        )

    settings = Settings(_env_file=None, data_dir=tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reader = RangeReader(tmp_path, settings, client)
        reader.chunk(0)
        with pytest.raises(FetchError, match="source_changed"):
            reader.chunk(1)
    assert not (tmp_path / "chunks" / "000001.json").exists()


def test_server_ignoring_ranges_is_rejected(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"abc"))
    ) as client:
        with pytest.raises(FetchError, match="safe_ranges"):
            RangeReader(tmp_path, settings, client).chunk(0)


def test_local_snapshot_immutable_and_dry_run_no_writes(tmp_path):
    raw = tmp_path / "input.tsv"
    raw.write_text("code\tproduct_name\n0034000470693\tTest\n", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        source_file=str(raw),
        source_format="tsv",
        target_products=1,
        max_raw_records=1,
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: pytest.fail("Network in local import"))
    ) as client:
        snapshot(settings, client, dry_run=True)
        assert not settings.data_dir.exists()
        path, metadata = snapshot(settings, client)
        before = path.read_bytes()
        assert metadata["retrieved_at"] is None
        assert snapshot(settings, client)[0].read_bytes() == before
        raw.write_text("code\tproduct_name\n0034000470693\tChanged\n", encoding="utf-8")
        with pytest.raises(ValueError, match="changed"):
            snapshot(settings, client)
        assert path.read_bytes() == before


def test_retry_after_is_honored_and_retries_bounded(monkeypatch):
    waits = []
    monkeypatch.setattr("ingestion.openfoodfacts.network.time.sleep", waits.append)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "7"})
        return httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_bytes(
            client,
            "https://static.openfoodfacts.org/test",
            limit=1024,
            retries=2,
            limiter=RateLimiter(1),
        )
    assert result[0] == b"ok"
    assert waits == [7]
    assert retry_delay(None, 2) == 4


def test_unsafe_redirect_and_oversize_download_are_rejected():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        )
    ) as client:
        with pytest.raises(FetchError, match="unsafe_redirect"):
            fetch_bytes(
                client,
                "https://static.openfoodfacts.org/test",
                limit=2,
                retries=0,
                limiter=RateLimiter(1),
                allowed_url=lambda url: url.startswith("https://"),
            )
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"big"))
    ) as client:
        with pytest.raises(FetchError, match="too_large"):
            fetch_bytes(
                client,
                "https://static.openfoodfacts.org/test",
                limit=2,
                retries=0,
                limiter=RateLimiter(1),
            )
