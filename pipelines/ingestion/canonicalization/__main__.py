import argparse
import json
from contextlib import nullcontext
from pathlib import Path

from ..openfoodfacts.config import Settings
from ..openfoodfacts.pipeline import single_run
from ..openfoodfacts.storage import read_json
from .pipeline import execute


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Locally canonicalize the Milestone 2 Product Master"
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--data-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate", action="store_true", help="Recompute and compare; read-only")
    mode.add_argument("--audit", action="store_true", help="Write an audit only; no canonical CSV")
    mode.add_argument("--inspect-report", action="store_true", help="Print existing quality report")
    args = parser.parse_args()
    try:
        data_dir = (args.data_dir or Settings().data_dir).resolve()
        input_path = args.input or data_dir / "processed/product_master.csv"
        output = args.output or data_dir / "processed/product_master_canonical.csv"
        name = (
            "product_master_audit.json" if args.audit else "product_master_canonical_quality.json"
        )
        report = args.report or data_dir / "reports" / name
        source_report = args.source_report or data_dir / "reports/openfoodfacts_quality.json"
        if args.inspect_report:
            print(json.dumps(read_json(report), ensure_ascii=True, indent=2))
            return 0
        with nullcontext() if args.validate else single_run(data_dir):
            result = execute(
                input_path,
                output,
                report,
                source_report,
                data_dir,
                validate=args.validate,
                audit_only=args.audit,
            )
        keys = (
            "status",
            "row_count",
            "rows",
            "column_count",
            "images",
            "completeness",
            "valid_search_text_products",
            "nutrition_review_products",
            "output_sha256",
        )
        print(json.dumps({key: result[key] for key in keys if key in result}, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"Canonicalization failed ({type(error).__name__}): {error}")
        return 1
    except KeyboardInterrupt:
        print("Canonicalization interrupted; rerun to rebuild the separate output.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
