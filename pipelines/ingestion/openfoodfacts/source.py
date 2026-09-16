import base64
import csv
import gzip
import hashlib
import io
import itertools
import json
import re
from contextlib import contextmanager
from pathlib import Path

import httpx

from . import PIPELINE_VERSION
from .config import SOURCE_HOSTS, Settings, safe_url
from .network import FetchError, RateLimiter, fetch_bytes
from .storage import atomic_json, canonical, digest, event, fingerprint, now, read_json

CHUNK_SIZE = 1_048_576


class RangeReader(io.RawIOBase):
    """Read only needed 1 MiB export chunks; each durable chunk is independently resumable."""

    def __init__(self, directory: Path, settings: Settings, client: httpx.Client):
        self.directory = directory
        self.settings = settings
        self.client = client
        self.position = 0
        self.current_index = -1
        self.current = b""
        self.limiter = RateLimiter(1)
        self.identity_path = directory / "export_identity.json"
        self.identity = read_json(self.identity_path) if self.identity_path.exists() else None

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        index, offset = divmod(self.position, CHUNK_SIZE)
        if self.current_index != index:
            self.current = self.chunk(index)
            self.current_index = index
        content = self.current[offset : offset + len(buffer)]
        buffer[: len(content)] = content
        self.position += len(content)
        return len(content)

    def chunk(self, index: int) -> bytes:
        start = index * CHUNK_SIZE
        if self.identity and start >= self.identity["total_bytes"]:
            return b""
        if start >= self.settings.max_source_bytes:
            raise FetchError("source_byte_budget_exhausted")
        path = self.directory / "chunks" / f"{index:06d}.json"
        if path.exists():
            saved = read_json(path)
            content = base64.b64decode(saved["bytes"])
            if hashlib.sha256(content).hexdigest() != saved["sha256"]:
                raise FetchError("raw_chunk_checksum_mismatch")
            return content
        end = min(start + CHUNK_SIZE, self.settings.max_source_bytes) - 1
        headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
        if self.identity:
            headers["If-Match"] = self.identity["etag"]
        content, response_headers, resolved_url, status = fetch_bytes(
            self.client,
            self.settings.source_url,
            limit=CHUNK_SIZE,
            retries=self.settings.max_retries,
            limiter=self.limiter,
            headers=headers,
            allowed_url=lambda url: safe_url(url, SOURCE_HOSTS),
        )
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response_headers.get("content-range", ""))
        if status != 206 or not match or int(match[1]) != start:
            raise FetchError("source_does_not_support_safe_ranges")
        if len(content) != int(match[2]) - start + 1 or int(match[2]) != min(
            end, int(match[3]) - 1
        ):
            raise FetchError("incomplete_source_chunk")
        etag = response_headers.get("etag")
        if not etag or (self.identity and etag != self.identity["etag"]):
            raise FetchError("source_changed_use_new_snapshot")
        if not self.identity:
            self.identity = {
                "etag": etag,
                "last_modified": response_headers.get("last-modified"),
                "total_bytes": int(match[3]),
                "resolved_url": resolved_url,
                "retrieved_at": now(),
            }
            atomic_json(self.identity_path, self.identity)
        atomic_json(
            path,
            {
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": base64.b64encode(content).decode("ascii"),
            },
        )
        event("raw_chunk_cached", chunk=index, compressed_bytes=start + len(content))
        return content


def records(stream, source_format: str):
    if source_format == "jsonl":
        for line in stream:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                # Reject non-JSON NaN/Infinity (including overflowing numeric literals).
                canonical(raw)
                yield raw
            except (json.JSONDecodeError, ValueError):
                yield None
    else:
        csv.field_size_limit(10_000_000)
        yield from csv.DictReader(stream, delimiter="\t" if source_format == "tsv" else ",")


@contextmanager
def input_stream(settings: Settings, directory: Path, client: httpx.Client):
    local = Path(settings.source_file).resolve() if settings.source_file else None
    binary = (
        local.open("rb") if local else io.BufferedReader(RangeReader(directory, settings, client))
    )
    compressed = str(local or settings.source_url).endswith(".gz")
    try:
        decoded = gzip.GzipFile(fileobj=binary) if compressed else binary
        with io.TextIOWrapper(decoded, encoding="utf-8-sig") as stream:
            yield stream
    finally:
        binary.close()


def snapshot(settings: Settings, client: httpx.Client, dry_run: bool = False) -> tuple[Path, dict]:
    directory = settings.data_dir / "raw" / "openfoodfacts" / settings.snapshot
    sample = directory / "sample.jsonl"
    metadata_path = directory / "metadata.json"
    local = Path(settings.source_file).resolve() if settings.source_file else None
    descriptor = {
        "source_url": settings.source_url,
        "source_format": settings.source_format,
        "source_file": str(local) if local else None,
        "local_sha256": digest(local) if local else None,
        "max_raw_records": settings.max_raw_records,
        "source_retrieved_at": settings.source_retrieved_at,
    }
    signature = fingerprint(descriptor)
    if metadata_path.exists():
        metadata = read_json(metadata_path)
        if metadata["signature"] != signature:
            raise ValueError("Snapshot configuration/source changed: choose --snapshot NEW_NAME")
        if metadata.get("complete"):
            if not sample.exists() or digest(sample) != metadata["raw_sha256"]:
                raise ValueError("Raw snapshot checksum mismatch; restore it or use a new snapshot")
            event("raw_snapshot_reused", raw_records=metadata["raw_records"])
            return sample, metadata
    else:
        metadata = {
            "source": "Open Food Facts",
            "source_url": settings.source_url,
            "source_file": str(local) if local else None,
            "signature": signature,
            "descriptor": descriptor,
            "pipeline_version": PIPELINE_VERSION,
            "import_started_at": now(),
            "complete": False,
            "retrieved_at": settings.source_retrieved_at or (None if local else now()),
            "retrieval_date_known": bool(settings.source_retrieved_at) or not local,
        }
    if dry_run:
        if not local:
            raise ValueError("Dry-run needs an existing complete snapshot or --source-file")
        return local, {**metadata, "dry_local": True}
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(metadata_path, metadata)
    # Only the temporary derivative is replaced; completed raw samples/chunks are immutable.
    partial = directory / "sample.jsonl.partial"
    count = 0
    with (
        input_stream(settings, directory, client) as source,
        partial.open("w", encoding="utf-8") as out,
    ):
        for raw in itertools.islice(
            records(source, settings.source_format), settings.max_raw_records
        ):
            out.write(canonical(raw) + "\n")
            count += 1
    partial.replace(sample)
    identity_path = directory / "export_identity.json"
    identity = read_json(identity_path) if identity_path.exists() else None
    if identity:
        metadata["retrieved_at"] = identity["retrieved_at"]
    metadata.update(
        complete=True,
        raw_records=count,
        raw_sha256=digest(sample),
        sample_completed_at=now(),
        export_identity=identity,
        sample_limit_reached=count == settings.max_raw_records,
    )
    atomic_json(metadata_path, metadata)
    event("raw_snapshot_complete", raw_records=count)
    return sample, metadata
