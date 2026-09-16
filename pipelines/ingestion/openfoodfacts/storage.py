import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

LOGGER = logging.getLogger("retailvision.ingestion")


def now() -> str:
    return datetime.now(UTC).isoformat()


def event(name: str, **fields) -> None:
    LOGGER.info(json.dumps({"timestamp": now(), "event": name, **fields}, ensure_ascii=True))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def atomic_json(path: Path, value) -> None:
    atomic_bytes(path, (canonical(value) + "\n").encode("utf-8"))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
