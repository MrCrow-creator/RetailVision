# RetailVision

RetailVision is a college-scale but technically rigorous **Retail Multimodal Knowledge Intelligence Platform**. It is an implementation/adaptation inspired by the mKG-RAG paper, not a full paper reproduction.

The target system identifies products from shelf imagery and combines semantic retrieval, knowledge-graph relationships, and exact retail records before an LLM produces a grounded explanation.

## Current Scope

Milestone 1 establishes the application foundation:

- React, TypeScript, Vite, and Tailwind CSS frontend
- Express and TypeScript orchestration API
- FastAPI AI-service boundary
- Health checks and frontend-to-backend connectivity
- Shared environment contract
- Linting, formatting, tests, and API documentation

Milestone 2 adds an offline **Open Food Facts → immutable raw snapshot → normalization → Product Master** pipeline, with resumable image downloads and a data-quality report.

Milestone 3 adds local, conservative canonicalization of that Product Master, image metadata, deterministic search text, and a separate versioned canonical CSV.

Databases, embeddings, YOLO, OCR, retrieval, LLM calls, synthetic retail data, and the full dashboard are **not implemented yet**.

## Architecture

```text
React frontend
      |
      v
Node.js / Express orchestration API
      |
      v
Python / FastAPI AI service

Future evidence plane:
Gemini Embedding 2 -> Qdrant
Neo4j relationships + PostgreSQL exact data
                |
                v
         Evidence fusion -> OpenAI
```

See [`PROJECT_SPEC.md`](PROJECT_SPEC.md) for responsibilities, data rules, retrieval flows, and milestones.

## Prerequisites

- Node.js LTS `22.13+` or `24+` (the current workspace uses Node.js `22`)
- npm `10+`
- Python `3.11+`

Docker is deliberately deferred until persistent infrastructure is introduced. Native development is simpler and fully sufficient for the current health-only services.

## Setup (PowerShell)

```powershell
# On a fresh checkout only; keep an existing .env and add desired OFF_* settings to it.
Copy-Item .env.example .env
npm install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".\ai-service[dev]"
python -m pip install -e ".\pipelines[dev]"
```

Keep real API keys only in `.env`. No key is required for Milestones 1–3.

The current root Python scripts explicitly use the Windows `.venv\Scripts\python.exe` interpreter. For ingestion on Linux/macOS, activate the virtual environment, install `./pipelines[dev]`, and run `python -m ingestion.openfoodfacts` directly.

## Run

Start all three development services from the repository root:

```powershell
npm run dev
```

Available URLs:

| Service                      | URL                                      |
| ---------------------------- | ---------------------------------------- |
| Frontend                     | `http://localhost:5173`                  |
| Backend health               | `http://localhost:4000/api/v1/health`    |
| Backend AI dependency health | `http://localhost:4000/api/v1/health/ai` |
| AI-service health            | `http://localhost:8000/health`           |
| AI-service OpenAPI UI        | `http://localhost:8000/docs`             |

The frontend uses Vite's development proxy, so browser API requests remain same-origin during local development.

Run one service at a time when needed:

```powershell
npm run dev:frontend
npm run dev:backend
npm run dev:ai
```

## Quality Checks

```powershell
npm test
npm run lint
npm run build
npm run format:check
npm run check
```

`npm run check` runs frontend/backend tests and builds, FastAPI tests, ingestion tests, linting, and formatting checks. Automated tests use local fixtures and mocked HTTP, with no dataset or image downloads.

## Milestone 2: Open Food Facts Ingestion

**Milestone 2 is complete only after the pipeline has successfully generated the Product Master and tests pass.** A successful run writes real records only; a shortfall produces the actual count and exit code `2`.

### Source and sample

- Source: [Open Food Facts official exports](https://world.openfoodfacts.org/data).
- Default: `https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz`.
- Only the prefix needed for the configured raw sample is fetched, using resumable 1 MiB HTTP ranges. The default budget is 12,000 raw rows and at most 128 MiB compressed transfer, not the entire database.
- Source URL, final redirected URL, retrieval time in UTC, export ETag/Last-Modified, raw row count, and SHA-256 are recorded in snapshot metadata and the quality report.
- The sample follows export order; selection is deterministic and favors complete records. It is not a random or representative survey of retail products.
- Current nested OFF image/nutrition schemas and legacy exports are supported. See [`PROJECT_SPEC.md`](PROJECT_SPEC.md#15-milestone-2-product-master-contract) for normalization rules and the canonical schema.
- Attribution: **Open Food Facts contributors**. Database: ODbL; individual contents: DbCL; product images: CC BY-SA 3.0. Preserve provenance and attribution when sharing the dataset. See the [OFF data reuse terms](https://world.openfoodfacts.org/terms-of-use).

### Run and resume

From the repository root, after installing the Python pipeline package:

```powershell
npm run ingest:off
```

Rerun the same command to resume. Completed raw samples and normalized records are reused; downloaded images are checked against their saved SHA-256 and skipped. Progress for each image is saved immediately. An interrupted raw import replays cached compressed chunks locally and fetches only missing chunks. If the remote export changes during an unfinished import, the pipeline refuses to combine versions; choose a new snapshot.

Use `npm.cmd` for commands with forwarded options in Windows PowerShell 5.1 (the `npm.ps1` wrapper in this environment can drop them):

```powershell
# Validate cached raw data locally; no network or file writes.
npm.cmd run ingest:off -- --dry-run

# Metadata-only ingestion; URLs are retained but images marked not_checked.
npm.cmd run ingest:off -- --no-download-images

# Retry persisted image failures; successful downloads are still skipped.
npm.cmd run ingest:off -- --retry-failed

# Start a separate immutable raw snapshot with a larger bounded sample.
npm.cmd run ingest:off -- --snapshot expanded --max-raw-records 16000
```

An image URL alone does **not** prove availability. Download-enabled runs verify file size, content type, image format, dimensions, and decoded pixels. The default downloads the actual selected front image's uploaded 400px version from the official AWS mirror, up to four concurrent requests and four requests/second. Legacy direct OFF image URLs are downloaded serially at one request/second. Failed/missing images remain explicitly reported; no substitute identity or invented image is supplied.

HTTP timeouts, transient errors and 429 responses use bounded retries and backoff with `Retry-After` support. A server cooldown above 120 seconds defers that request to a later run. Persisted failures require `--retry-failed`. AWS is periodically synchronized, so recent images can be absent.

### Local source

Supports JSONL (one JSON object per line), CSV, and TSV, optionally gzip-compressed. Official OFF “CSV” exports are **tab-delimited**, so specify `tsv`. Do not convert barcode columns to spreadsheet numbers.

```powershell
npm.cmd run ingest:off -- --source-file "D:\datasets\off-sample.tsv" --source-format tsv --source-url "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz" --snapshot local-sample
```

Supply `--source-retrieved-at "YYYY-MM-DDTHH:MM:SSZ"` only if the actual retrieval time is known. Otherwise the report marks it unknown and records the import time separately. The local source is never edited; its SHA-256 identifies the input. A changed source or sampling configuration requires a new snapshot name. `--dry-run` also works with a supplied local source before the first import.

### Configuration

Defaults are defined once in `pipelines/ingestion/openfoodfacts/config.py`. Root `.env` uses the `OFF_` prefix; CLI options override environment settings. All non-secret settings used for a run are recorded in the report.

| Variable                        | Default                  | Purpose                                                |
| ------------------------------- | ------------------------ | ------------------------------------------------------ |
| `OFF_TARGET_PRODUCTS`           | `3000`                   | Maximum final Product Master size                      |
| `OFF_MAX_RAW_RECORDS`           | `12000`                  | Bounded raw sample (must be ≥ target)                  |
| `OFF_SOURCE_URL`                | Official JSONL export    | Source/provenance URL                                  |
| `OFF_SOURCE_FORMAT`             | `jsonl`                  | `jsonl`, `tsv`, or `csv`                               |
| `OFF_SOURCE_FILE`               | Empty                    | Optional local source path                             |
| `OFF_SOURCE_RETRIEVED_AT`       | Empty                    | Known retrieval timestamp of supplied source           |
| `OFF_SNAPSHOT`                  | `initial`                | Immutable raw snapshot name                            |
| `OFF_DATA_DIR`                  | Repository `data/`       | Output/cache root                                      |
| `OFF_MAX_SOURCE_BYTES`          | `134217728`              | Compressed export byte budget                          |
| `OFF_DOWNLOAD_IMAGES`           | `true`                   | Download and verify images                             |
| `OFF_IMAGE_TIMEOUT`             | `20`                     | HTTP timeout in seconds                                |
| `OFF_MAX_RETRIES`               | `2`                      | Retries after the first request                        |
| `OFF_IMAGE_WORKERS`             | `4`                      | Maximum concurrent AWS downloads                       |
| `OFF_IMAGE_REQUESTS_PER_SECOND` | `4`                      | Global AWS request-start rate                          |
| `OFF_MAX_IMAGE_BYTES`           | `5242880`                | Maximum bytes per image                                |
| `OFF_USER_AGENT`                | `RetailVision/0.2 (...)` | Project identification; add project contact if desired |

Exit codes: `0` success, `1` configuration/source/I/O failure, `2` insufficient valid products, `130` interrupted. Only one writer per data directory is allowed.

### Outputs and inspection

```text
data/
|-- raw/openfoodfacts/
|   |-- initial/
|   |   |-- metadata.json          Source identity, retrieval dates, sample hash
|   |   |-- export_identity.json   ETag and remote export identity
|   |   |-- chunks/                Checksummed compressed source chunks
|   |   `-- sample.jsonl           Immutable raw records
|   `-- images/                    One image + state/checksum per product
|-- processed/
|   |-- openfoodfacts/             Versioned normalized-record cache
|   `-- product_master.csv         Canonical dataset
`-- reports/
    `-- openfoodfacts_quality.json Counts, missing fields, image outcomes, provenance
```

Generated datasets, images, caches, and reports are Git-ignored. The CSV is UTF-8; `nutrition` and tag lists are JSON-encoded cells. `barcode` and `product_id` must be imported as **text**, including leading zeros. `image_path` is relative to `OFF_DATA_DIR`.

```powershell
# Preview the first three canonical products.
npm.cmd run ingest:off -- --inspect master --rows 3

# Print the complete quality report.
npm.cmd run ingest:off -- --inspect report

# Validate all IDs/schema, uniqueness, report checksum, and local image checksums.
npm.cmd run ingest:off -- --inspect validate

# Run focused ingestion tests, then the complete project checks.
npm run test:ingestion
npm run check
```

The final quality score is the average of seven equally weighted flags: valid barcode, name, brand, category, **verified downloaded image**, ingredients, and nutrition. Metadata-only/dry runs get no image-quality credit. Candidate ranking uses a safe image URL as a provisional image signal before downloads. Missing optional fields never cause record rejection. See the specification for duplicate tie-breaking and nutrition units.

### Verified initial dataset

The `initial` snapshot was retrieved on **2026-09-16 (UTC)** from the official JSONL export. Only **43 MiB** of compressed export chunks were needed. Normalization version `0.2.2` produced:

| Measure                                            | Result                    |
| -------------------------------------------------- | ------------------------- |
| Raw records                                        | 12,000                    |
| Valid unique records                               | 11,922                    |
| Rejected records                                   | 78 (missing product name) |
| Duplicate records removed                          | 0                         |
| Final Product Master                               | 3,000                     |
| Products with image URLs                           | 2,038                     |
| Verified downloaded images                         | 2,035                     |
| Failed downloads                                   | 3 (HTTP 404)              |
| Products without image URLs                        | 962                       |
| Average completeness score                         | 0.9537                    |
| Missing brand / category / ingredients / nutrition | 2 / 1 / 4 / 0             |
| Missing country / packaging                        | 1 / 2,633                 |

Two structurally valid OFF identifiers fail the optional GS1 checksum diagnostic and are flagged in the CSV/report. These numbers describe this local snapshot; a new export/snapshot can differ. The daily-change export was also sampled during compatibility testing, but the final Product Master uses the `initial` full-export sample.

## Milestone 3: Canonical Product Master

This stage processes **only the existing Product Master and its referenced local images**. It runs within the existing Python pipeline package, with no new dependencies or network requests. `npm run ingest:off` retains its Milestone 2 behavior.

### Input and outputs

- Input: `data/processed/product_master.csv` (preserved).
- Source provenance: `data/reports/openfoodfacts_quality.json` (preserved and checksum-checked).
- Initial audit: `data/reports/product_master_audit.json`.
- Separate canonical output: `data/processed/product_master_canonical.csv`.
- Canonical quality report: `data/reports/product_master_canonical_quality.json`.

The canonical CSV is an independently validated candidate for downstream use. It does **not** replace or delete the Milestone 2 CSV. Every input row, `product_id`, and `barcode` is preserved exactly. Duplicate/mismatched IDs or malformed required data stop publication rather than silently dropping rows.

### Commands (PowerShell)

```powershell
# Optional: regenerate the audit without producing a canonical CSV.
npm.cmd run normalize:products -- --audit

# Generate canonical CSV and quality report.
npm run normalize:products

# Read-only: recompute from source and local images, then compare CSV and report.
npm.cmd run normalize:products -- --validate

# Inspect the full report, including per-product review issues.
npm.cmd run normalize:products -- --inspect-report

# Focused tests, then all Milestone 1–3 checks.
npm run test:normalization
npm run check
```

Options: `--input PATH`, `--output PATH`, `--report PATH`, `--source-report PATH`, and `--data-dir PATH`. With custom input, provide its matching provenance report; if no report exists, the retrieval date is explicitly unknown. Defaults use `OFF_DATA_DIR` (repository `data/`). Output/report paths are prevented from overwriting the source CSV, source report, or raw data. On Linux/macOS, use `python -m ingestion.canonicalization` in the installed virtual environment.

### Conservative rules

- **Display text:** NFC Unicode normalization, whitespace cleanup, decoding of semicolon-terminated HTML entities, removal of known formatting tags and invisible formatting artifacts. Preserve display casing, flavor, size, pack counts, ingredient order/percentages, accents, and meaningful joiner characters.
- **Original information:** `source_values` is a JSON object containing the exact original CSV cell for every changed source field. Unchanged source fields remain in the canonical row; the full original CSV also remains available.
- **Brands:** `brand_normalized` is a sorted JSON array of case-folded brand tokens. No accent folding, fuzzy matches, spelling mergers, or hidden brand aliases. `Nestle` and `Nestlé` remain distinct.
- **Categories:** preserve the cleaned display list; derive `category_normalized` from the existing OFF category tags. Retain all genuine hierarchy/multilingual tags. OFF arrays are not ordered paths, so the last tag is never treated as a leaf. Untagged fallback text is explicitly prefixed `text:`.
- **Countries:** preserve the complete display list and derive a sorted `country_normalized` array from OFF country tags. Multiple countries are retained.
- **Missing values:** empty scalar cells and empty JSON objects/arrays, with `missing_value_reasons`. Match only complete placeholder values/tokens (`undefined`, `en:null`, etc.). Distinguish not provided, explicit source-unavailable, explicit source-not-applicable, and ambiguous placeholders. No missing content is fabricated.
- **Quantities:** preserve source declarations; `quantity_normalized` standardizes only simple spacing/unit casing and liter/litre spelling. No conversions or guessed totals for multipacks, mixed units, or unitless counts.
- **Nutrition:** retain the compact JSON object, units/basis, and source values. Flag unusually high weight-nutrient values in `normalization_issues` and `nutrition_review_required`; do not guess corrected values. A mass value above 100 per 100g is flagged; values with a 100ml/ambiguous legacy basis receive a basis-review flag. Downstream factual retrieval must respect these flags.
- **Images:** check every supplied path against local files, enforce containment within the data directory, verify formats/dimensions and decoded pixels using the Milestone 2 validator, and record format, dimensions, byte size, and SHA-256. Invalid/missing paths are cleared from usable `image_path` and retained in `source_values`. No images are redownloaded. `image_available` records observed file presence; only `image_valid` qualifies an image for future embedding work.
- **Search:** deterministic labeled text in a fixed order: product, brand, category keys, ingredients, country keys, packaging, quantity. Excludes nutrition (which can require review), stock, price, promotions, and other nonexistent operational facts.

The original seven-flag **completeness score** is reused through `Product.score()`. Removing placeholder categories can lower it; this is an honest correction of missingness, not loss of valid facts. Nutrition review flags do not convert this score into an accuracy estimate.

### Audited local result

| Measure                                             | Milestone 3 result               |
| --------------------------------------------------- | -------------------------------- |
| Input / output products                             | 3,000 / 3,000                    |
| Duplicate IDs / barcodes                            | 0 / 0                            |
| Canonical columns                                   | 43 (25 existing + 18 added)      |
| Valid images / missing local images / invalid files | 2,035 / 965 / 0                  |
| Image formats                                       | JPEG: 2,035                      |
| Width / height range                                | 60–400 px / 90–400 px            |
| Products with search text                           | 3,000                            |
| Completeness before / after                         | 0.9537 / 0.8679                  |
| Placeholder-only categories discovered              | 1,802                            |
| Nutrition review                                    | 435 products, 632 flagged values |

The report contains exact columns, checksums, source retrieval date, processing timestamp/version, before/after missingness, image statistics, changed-field counts, and per-product issues. Repeated runs with identical CSV bytes, referenced image bytes, and normalization rules produce byte-identical canonical CSVs. Report processing timestamps may differ; validation compares every other report field and all output bytes. See the [canonical schema contract](PROJECT_SPEC.md#16-milestone-3-canonical-dataset-contract).

## API Contract

The backend contract is in [`docs/openapi.yaml`](docs/openapi.yaml).

Health response example:

```json
{
  "status": "ok",
  "service": "backend",
  "version": "0.1.0",
  "timestamp": "2026-09-16T12:00:00.000Z"
}
```

## Repository Layout

```text
RetailVision/
|-- frontend/          React browser application
|-- backend/           Express orchestration API
|-- ai-service/        FastAPI AI boundary
|-- pipelines/        Offline ingestion package and focused tests
|-- data/             Generated raw/processed data and reports (Git-ignored)
|-- docs/              API documentation
|-- .env.example       Environment variable template
|-- AGENTS.md          Concise context for future engineering sessions
|-- PROJECT_SPEC.md    Architecture and implementation contract
`-- package.json       npm workspace and root commands
```

Model and additional pipeline directories will be added when their milestones begin.

## Next Milestone

Milestone 4 (synthetic retail data) requires explicit project-owner confirmation. Future pipelines must reference the approved Product Master IDs and respect image-validity and nutrition-review flags.
