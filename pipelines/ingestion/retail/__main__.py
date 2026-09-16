import argparse
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from ..openfoodfacts.config import Settings
from ..openfoodfacts.storage import event, read_json
from .config import RetailSettings
from .pipeline import execute
from .validation import RetailValidationError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seeded synthetic retail context for canonical OFF products"
    )
    for name in ("input", "output-dir", "report", "input-report", "data-dir"):
        parser.add_argument(f"--{name}", type=Path)
    for name in (
        "seed",
        "store-count",
        "shelves-per-store",
        "supplier-count",
        "promotion-count",
        "placement-count",
    ):
        parser.add_argument(f"--{name}", type=int)
    parser.add_argument("--as-of-date", help="Fixed ISO simulation date, not today's wall clock")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--validate", action="store_true", help="Read-only integrity and reproducibility checks"
    )
    mode.add_argument(
        "--dry-run", action="store_true", help="Validate input and show settings; no writes"
    )
    mode.add_argument("--inspect-report", action="store_true")
    args = vars(parser.parse_args())
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        data_dir = (args.pop("data_dir") or Settings().data_dir).resolve()
        custom_input = args.pop("input")
        input_path = custom_input or data_dir / "processed/product_master_canonical.csv"
        output_dir = args.pop("output_dir") or data_dir / "synthetic"
        report_path = args.pop("report") or data_dir / "reports/synthetic_retail_quality.json"
        source_report = args.pop("input_report")
        if source_report is None and custom_input is None:
            source_report = data_dir / "reports/product_master_canonical_quality.json"
        validate_only, dry_run, inspect = (
            args.pop(name) for name in ("validate", "dry_run", "inspect_report")
        )
        if inspect:
            result = read_json(report_path)
        else:
            settings = RetailSettings(
                **{key: value for key, value in args.items() if value is not None}
            )
            event(
                "synthetic_retail_started",
                seed=settings.seed,
                mode="validate" if validate_only else "dry_run" if dry_run else "generate",
            )
            result = execute(
                input_path,
                output_dir,
                report_path,
                settings,
                data_dir,
                source_report=source_report,
                validate_only=validate_only,
                dry_run=dry_run,
            )
            if not (dry_run or validate_only):
                result = {
                    key: result[key]
                    for key in (
                        "generation_id",
                        "counts",
                        "inventory_distribution",
                        "sales_distribution",
                        "promotion_distribution",
                        "scenario_counts",
                        "integrity",
                    )
                }
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except RetailValidationError as error:
        print(json.dumps(error.result, ensure_ascii=True, indent=2))
        return 1
    except ValidationError as error:
        print(
            json.dumps(
                {
                    "error": "schema_or_configuration",
                    "fields": [
                        ".".join(map(str, item["loc"]))
                        for item in error.errors(include_input=False)
                    ],
                }
            )
        )
        return 1
    except (ValueError, OSError, KeyError) as error:
        print(f"Synthetic retail generation failed: {error}")
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Rerun with the same input/configuration to rebuild the output set.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
