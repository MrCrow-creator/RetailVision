import argparse
import json
import logging
import sys
from contextlib import nullcontext

from .config import Settings
from .inspection import inspect_data
from .network import FetchError
from .pipeline import run, single_run
from .storage import event


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open Food Facts -> raw snapshot -> Product Master"
    )
    parser.add_argument("--source-file", help="Local OFF JSONL/CSV/TSV, optionally gzipped")
    parser.add_argument("--source-format", choices=["jsonl", "csv", "tsv"])
    parser.add_argument("--source-url", help="Official export URL recorded as provenance")
    parser.add_argument(
        "--source-retrieved-at", help="Actual retrieval timestamp for a supplied file"
    )
    parser.add_argument("--snapshot", help="New name for a different source/configuration")
    parser.add_argument("--target-products", type=int)
    parser.add_argument("--max-raw-records", type=int)
    parser.add_argument("--download-images", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="Local validation only; no writes/network"
    )
    parser.add_argument("--retry-failed", action="store_true", help="Retry persisted failed images")
    parser.add_argument(
        "--inspect", choices=["master", "report", "raw", "validate"], help="Read/validate outputs"
    )
    parser.add_argument("--rows", type=int, default=3, help="Rows to show when inspecting (1-20)")
    args = vars(parser.parse_args())
    dry_run = args.pop("dry_run")
    retry_failed = args.pop("retry_failed")
    inspect_kind = args.pop("inspect")
    rows = args.pop("rows")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings(**{key: value for key, value in args.items() if value is not None})
        if inspect_kind:
            inspect_data(settings, inspect_kind, rows)
            return 0
        with nullcontext() if dry_run else single_run(settings.data_dir):
            report = run(settings, dry_run=dry_run, retry_failed=retry_failed)
        if dry_run:
            print(json.dumps(report, ensure_ascii=True, indent=2))
        # An honest shortfall still produces a report/CSV but does not claim success.
        return 0 if report["target_reached"] else 2
    except KeyboardInterrupt:
        event("ingestion_interrupted", action="Run the same command to resume")
        return 130
    except (ValueError, OSError, FetchError, EOFError) as error:
        # Do not dump provider responses, raw records, or environment validation inputs.
        event(
            "ingestion_failed",
            error_type=type(error).__name__,
            reason=str(error) if isinstance(error, FetchError) else "check_config_or_snapshot",
            action="Verify configuration/cache; use a new snapshot for a changed export",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
