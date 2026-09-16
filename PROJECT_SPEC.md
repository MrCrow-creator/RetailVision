# RetailVision Project Specification

## 1. Purpose and Academic Positioning

RetailVision is a **Retail Multimodal Knowledge Intelligence Platform** for a final-year BE Artificial Intelligence and Data Science project. It adapts ideas from “mKG-RAG: Leveraging Multimodal Knowledge Graphs in Retrieval-Augmented Generation for Knowledge-intensive VQA.” It does not claim to reproduce the complete paper or achieve state-of-the-art results.

The demonstrable goal is an end-to-end system that can identify likely retail products in shelf images, retrieve exact and relational evidence, apply transparent retail rules, and generate a grounded natural-language answer.

## 2. Non-Negotiable Design Principles

1. The product is not a generic chatbot, vector-only RAG application, or CRUD dashboard.
2. Answers must be grounded in retrieved evidence from Qdrant, Neo4j, and PostgreSQL when those services are implemented.
3. PostgreSQL remains the source of truth for exact stock, price, sales, and promotion values.
4. Neo4j stores relationships and supports traversal; it is not a duplicate numerical database.
5. Qdrant stores multimodal and text vectors linked by stable product IDs.
6. Business conditions such as `stock < reorder_level` are computed deterministically before prompting an LLM.
7. The LLM explains evidence. It must not invent identity, price, stock, supplier, discount, or relationships.
8. Low-confidence product matches remain uncertain and expose ranked candidates rather than forcing an identity.
9. External API calls are minimized through offline ingestion, batching, caching, retry handling, and resumability.
10. The initial academic scale is approximately 3,000 products, not an unnecessary production-scale corpus.

## 3. System Architecture

```text
USER
  |
  v
REACT FRONTEND
  |
  v
NODE.JS / EXPRESS API AND ORCHESTRATION
  |
  +-------------------------+
  |                         |
  v                         v
PYTHON AI SERVICE      RETRIEVAL / DATA SERVICES
(YOLO, OCR, embedding) (Qdrant, Neo4j, PostgreSQL)
  |                         |
  +------------+------------+
               |
               v
         EVIDENCE FUSION
               |
               v
          OPENAI LLM
               |
               v
      GROUNDED API RESPONSE
```

### 3.1 Frontend Responsibility

- Image upload and question entry
- Bounding-box and candidate-match presentation
- Product, stock, price, promotion, and confidence evidence
- Source attribution and insufficient-evidence states
- Knowledge graph visualization
- Deterministic analytics visualization
- Responsive, professional retail-intelligence interface

The frontend does not call model providers or databases directly.

### 3.2 Node.js Backend Responsibility

- Public API contract
- Authentication and authorization if introduced
- Request validation and upload coordination
- Query understanding and workflow orchestration
- Calls to Python inference endpoints
- Qdrant, Neo4j, and PostgreSQL retrieval coordination
- Deterministic retail filters and analytics
- Evidence fusion and OpenAI prompting
- Stable, source-attributed response objects

### 3.3 Python AI-Service Responsibility

- YOLO shelf-object detection
- Product crop generation
- PaddleOCR inference
- Gemini Embedding 2 client and controlled embedding jobs where Python is appropriate
- Image/text signal preparation for product candidate retrieval
- Future model evaluation utilities

The FastAPI service does not become a second orchestration backend or source of operational retail truth.

## 4. Data Service Boundaries

### PostgreSQL: Exact Structured Data

Initial logical records:

- `product_master`: `product_id`, barcode, name, brand, category, ingredients, nutrition, country, packaging, image path
- `retail_data`: `product_id`, store, shelf, stock, reorder level, price, 30-day sales, supplier, promotion

Normalization may be introduced when it materially improves integrity, but the first schema should remain easy to explain.

### Neo4j: Relationships

Initial nodes: Product, Brand, Category, Supplier, Store, Shelf, Promotion.

Initial relationships:

```text
(Brand)-[:HAS_PRODUCT]->(Product)
(Product)-[:BELONGS_TO]->(Category)
(Supplier)-[:SUPPLIES]->(Product)
(Product)-[:LOCATED_ON]->(Shelf)
(Shelf)-[:LOCATED_IN]->(Store)
(Product)-[:HAS_PROMOTION]->(Promotion)
```

### Qdrant: Semantic and Multimodal Retrieval

Initial logical collections:

- `product_images`
- `product_text`
- `documents` (later milestone)

Every product vector payload includes `product_id`, modality, source, and useful filter fields. The embedding dimension is configuration-driven and begins at 1536 if supported by the selected Gemini endpoint.

## 5. Identity and Integrity Contract

Open Food Facts barcode is the external source identifier. The canonical internal key is:

```text
OFF_<barcode>
```

The exact same `product_id` must bridge PostgreSQL, Neo4j, Qdrant, embeddings, synthetic retail data, API responses, and frontend state.

Required validation gates for later ingestion milestones:

- Reject duplicate canonical product IDs.
- Report missing or invalid barcodes before ID construction.
- Ensure each synthetic retail row references Product Master.
- Ensure each Qdrant product payload references Product Master.
- Ensure each Neo4j Product node references Product Master.
- Produce machine-readable integrity reports for missing references.

## 6. Retrieval Flows

### Image or Image-plus-Question

```text
Shelf image
-> YOLO bounding boxes
-> product crops
-> Gemini Embedding 2 query embeddings plus optional PaddleOCR text
-> Qdrant top-k visual candidates
-> confidence-aware signal fusion
-> canonical product IDs
-> PostgreSQL exact values and deterministic filters
-> Neo4j relationship traversal when relevant
-> fused, source-attributed evidence
-> OpenAI grounded explanation
```

### Text-only Question

```text
Text question
-> one cached/query-time Gemini Embedding 2 embedding
-> Qdrant semantic candidates
-> PostgreSQL exact values and deterministic filters
-> Neo4j relationship traversal
-> fused, source-attributed evidence
-> OpenAI grounded explanation
```

This is deliberately not `query -> vector database -> LLM`.

## 7. Embedding Policy

- Gemini Embedding 2 is the primary shared-space embedding system.
- The configured initial output dimension is `1536`, subject to API support.
- Product images, product text, and document chunks are embedded offline.
- Query time generates only embeddings required for the current request.
- Cache keys must include source checksum, modality, model, dimension, and preprocessing version.
- Batch sizes must respect provider request and image limits.
- Jobs must retry transient failures with bounded exponential backoff and rate-limit awareness.
- Progress must be persisted so interrupted jobs resume without regenerating completed vectors.
- CLIP or SigLIP is not introduced unless separately approved and technically justified.

## 8. Evidence and LLM Contract

The eventual evidence object should contain enough structure for deterministic checks and UI attribution. A representative shape is:

```json
{
  "query": "Which visible products are low in stock and discounted?",
  "identified_products": [],
  "structured_facts": [],
  "graph_relationships": [],
  "semantic_matches": [],
  "applied_rules": [],
  "sources": [],
  "limitations": []
}
```

The OpenAI system instruction must state: “Answer only using the provided evidence. If evidence is insufficient, say so.” Structured facts and rule results are generated before the prompt. The response retains evidence references for UI inspection and evaluation.

## 9. Transparent Analytics

Initial analytics are deterministic:

- Low stock: `stock < reorder_level`
- Stock deficit: `max(reorder_level - stock, 0)`
- Promotion status from current structured promotion records
- Fast/slow movement from documented sales thresholds
- Restocking priority from a documented combination of stock deficit, sales velocity, and promotion status

No output is described as an ML forecast unless a separately evaluated model is implemented.

## 10. API Conventions

- Public backend prefix: `/api/v1`
- JSON responses use explicit status codes and stable error objects.
- FastAPI model/inference routes are internal dependencies of the backend.
- Timestamps use UTC ISO 8601.
- Current endpoint details are versioned in `docs/openapi.yaml`.

Milestone 1 endpoints:

| Method | Endpoint               | Purpose                             |
| ------ | ---------------------- | ----------------------------------- |
| GET    | `/api/v1/health`       | Express process health              |
| GET    | `/api/v1/health/ai`    | Express-to-FastAPI dependency check |
| GET    | `/health` on port 8000 | FastAPI process health              |

## 11. Environment Contract

Secrets and deploy-specific values live in environment variables. `.env.example` documents the contract; `.env` is ignored.

Important future variables include `OPENAI_API_KEY`, `OPENAI_MODEL`, `GEMINI_API_KEY`, `GEMINI_EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `POSTGRES_URL`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `QDRANT_URL`, and `QDRANT_API_KEY`.

No provider client is initialized in Milestone 1.

## 12. Incremental Milestones

1. Project skeleton, health checks, connectivity, documentation, and tests
2. Open Food Facts ingestion and initial normalized Product Master (expanded Milestone 2 scope)
3. Product cleaning and normalization
4. Synthetic retail data
5. PostgreSQL
6. Neo4j
7. Gemini Embedding 2 integration
8. Qdrant
9. Product text retrieval
10. Product image retrieval
11. YOLO
12. PaddleOCR
13. Shelf-to-product identification
14. Hybrid retrieval
15. OpenAI grounded reasoning
16. Retail analytics
17. Full React product interface
18. End-to-end integration
19. Evaluation
20. Polishing and deployment

Every milestone requires implementation, tests, verification, error correction, and documentation before the next begins.

## 13. Evaluation Plan

- YOLO: precision, recall, and mAP
- Visual retrieval: Top-1 and Top-5 accuracy
- RAG: retrieval relevance, answer correctness, grounding, and hallucination rate
- System: component latency, retrieval time, and end-to-end response time
- Question set: approximately 50-100 manually verified retail questions

Claims must be limited to measured prototype results and must not use “state of the art.”

## 14. Milestone 1 Acceptance Criteria

- npm initialization is preserved and upgraded into a workspace root.
- React, Express, and FastAPI services have independent, typed structures.
- Frontend visibly reports real backend connectivity.
- Backend and AI-service health endpoints return tested contracts.
- Root environment, formatting, linting, test, and run commands are documented.
- No fake AI data, provider calls, datasets, database clients, or retrieval behavior exists.
- The next milestone does not begin without project-owner confirmation.

## 15. Milestone 2 Product Master Contract

Milestone 2 includes the cleaning/normalization needed to create Product Master, as explicitly requested by the project owner. It is an offline Python CLI (`pipelines/ingestion/openfoodfacts/`) invoked by `npm run ingest:off`. It does not add application routes, model inference, databases, or synthetic retail records.

### Source and persistence

- Official Open Food Facts export: `https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz`; configurable official export URL or local JSONL/CSV/TSV (including gzip).
- Default limits: 12,000 raw records, 128 MiB compressed transfer, 3,000 final products. Sampling follows source order, without randomization.
- Named raw snapshots record retrieval/import dates separately, source URL, redirect URL, export ETag/Last-Modified, source checksums, row count, and pipeline version. Unknown local-file retrieval dates remain unknown.
- Compressed HTTP range chunks are saved atomically with checksums. Completed raw snapshots are immutable and replayable. Interrupted exports resume from cached chunks, gated by the export ETag; different remote versions cannot be mixed.
- Normalization cache keys include raw SHA-256 and `PIPELINE_VERSION`. Image states persist independently per canonical product ID and URL, with file checksum and failure code. A repeated run reuses completed normalization and valid images.
- Outputs are `data/processed/product_master.csv` and `data/reports/openfoodfacts_quality.json`; all generated data is Git-ignored. The report includes the CSV checksum to detect an interrupted or mismatched publication.

### Canonical schema

The executable schema is the Pydantic `Product` model in `pipelines/ingestion/openfoodfacts/models.py`. Each row contains:

| Field                                                                     | Type / meaning                                                                          |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `product_id`                                                              | Required string `OFF_<canonical barcode>`                                               |
| `barcode`                                                                 | Required canonical OFF code, stored as text                                             |
| `product_name`                                                            | Required non-blank name; original language retained                                     |
| `brand`, `category`                                                       | Preferred descriptive text; empty string when absent                                    |
| `ingredients`, `country`, `packaging`                                     | Optional text; no invented defaults                                                     |
| `nutrition`                                                               | JSON object of selected finite non-negative nutrient values                             |
| `nutrition_basis`                                                         | `100g`, `100ml`, or legacy `100g_or_100ml`; empty if no nutrition                       |
| `nutrition_source`                                                        | `off_aggregated_as_sold` or `off_legacy_as_sold`                                        |
| `image_url`                                                               | One validated official source URL, empty if absent/unsafe                               |
| `image_path`                                                              | Verified local image path relative to the data directory, or empty                      |
| `image_status`                                                            | `downloaded`, `failed`, `missing`, `not_checked` (internal `pending` before processing) |
| `quantity`, `serving_size`                                                | Optional original descriptive text                                                      |
| `categories_tags`, `brands_tags`, `countries_tags`, `labels`, `allergens` | Sorted, deduplicated JSON string arrays                                                 |
| `barcode_checksum_valid`                                                  | Diagnostic GS1 check-digit flag                                                         |
| `data_quality_score`                                                      | Deterministic completeness score in [0, 1]                                              |
| `source`, `source_product_url`                                            | OFF attribution and per-product provenance                                              |

CSV uses UTF-8 and JSON-encoded nested cells. Consumers must read identifier columns as text. Required-field and stable-ID validation runs again before publication. Empty optional strings/objects/arrays mean missing data, not negative business facts.

### Normalization and validity

1. Unicode NFC and repeated-whitespace normalization preserve meaningful names and original language. Null/NaN placeholder strings are treated as missing. Brand/category text is not aggressively recategorized; category/country tags are retained separately.
2. Accept non-zero ASCII digit strings or integer inputs of 1–14 digits. Reject booleans, floats, decimals/scientific-notation strings, missing values, and non-digit input. Floats cannot reliably preserve identifiers and are never repaired by rounding.
3. Apply [official OFF normalization](https://openfoodfacts.github.io/openfoodfacts-server/api/ref-barcode-normalization/): strip redundant leading zeros, pad up to 8 digits for short codes, pad 9–12 significant digits to 13, retain 13/14-digit codes. This makes UPC/EAN representations converge, e.g. `034000470693` → `0034000470693` → `OFF_0034000470693`.
4. Validity here is **OFF structural code validity**, not GS1 certification. OFF includes internal/non-GS1 codes. GS1 checksum failures are explicitly flagged and counted rather than silently corrected or rejected. The required example `8901234567890` maps to `OFF_8901234567890` even though its GS1 checksum fails.
5. Current OFF schema 1002+ `images.selected.front.<language>.imgid` and legacy `images.front_<language>.imgid` identify the actual selected front upload. Language preference: product language, English, then sorted available languages. AWS uses that upload's 400px image, not an invented image ID or a cropped-image revision filename. For the image folder only, pad short codes to 13 digits and split 3/3/3/remainder; this never changes the canonical barcode or product ID.
6. Current schema 1003+ nutrition uses `nutrition.aggregated_set` **as sold**, with explicit `100g`/`100ml` basis and normalized units. Legacy `nutriments` or tabular `_100g` fields are also supported. Only energy-kJ/kcal, fat, saturated fat, carbohydrates, sugars, fiber, protein, salt, and sodium are retained. Weight nutrients are in grams, energy in kJ/kcal. `_100g` keys follow OFF's legacy convention, which can mean 100ml for liquids; consult `nutrition_basis`. Prepared, per-serving, unsupported units, non-finite and negative values are not mixed into these fields.

### Duplicate rule and ranking

Barcode is the only deduplication identity. Choose one whole record deterministically: highest provisional seven-field completeness score, then most non-empty canonical fields, then lexicographically smallest canonical JSON representation. Whole-record selection avoids creating contradictory merged ingredient/nutrition facts. Select the top target number after deduplication; final CSV rows are sorted by product ID. No random tie-breaking or synthetic records are used.

### Image verification and score

- One selected front upload per product, downloaded from OFF's [official AWS mirror](https://openfoodfacts.github.io/openfoodfacts-server/api/aws-images-dataset/) where source image IDs are available. Primary OFF server URLs from older exports remain supported with serial throttling.
- Default AWS concurrency/rate: four workers, four request starts/second; primary OFF host: one at a time, one/second. Bounded HTTP retries respect `Retry-After`; long cooldowns defer rather than retry early.
- Allowlisted HTTPS URLs, validated redirects, byte limits, MIME/format checks (JPEG/PNG/WebP), safe dimensions, complete pixel decoding, atomic files, and per-image state make individual failures non-fatal. Corrupted cached bytes are detected before reuse. Successful images are skipped; failed images are retried only with `--retry-failed`.
- Final score = `(barcode + name + brand + category + verified_image + ingredients + nutrition) / 7`, with Boolean presence flags, rounded to four decimals. Before image downloads, the ranking score uses a safe image URL as a provisional signal. Unchecked URLs never earn final image credit.
- The report distinguishes raw/valid/unique counts, invalid reasons, duplicates, final count, available image URLs, verified downloads, failures, unchecked/missing images, missing fields, checksum flags, and average score. Invalid reason counts can overlap on one rejected record; `invalid_records` counts each rejected row once.

### Verification boundary

Focused offline tests cover identifiers, current/legacy schemas, duplicates, missing optional data, raw range caching, changed-source refusal, retry handling, failed/corrupt images, image/normalization resume, deterministic CSV, and honest shortfalls. `npm run check` includes these tests and all Milestone 1 checks. Dataset inspection additionally validates every Product Master row, uniqueness, report consistency, and downloaded image checksums. Milestone 3 remains gated by explicit confirmation.

## 16. Milestone 3 Canonical Dataset Contract

Milestone 3 is a separate transformation within the existing Python package: `pipelines/ingestion/canonicalization/`, exposed by `npm run normalize:products`. It reads Milestone 2's CSV and referenced local images only. Ingestion, raw source snapshots, downloads, API routes, and application services are not redesigned. No external services are called.

### Identity, source preservation and publication

- Input IDs and barcodes are strings, validated **verbatim** and carried through unchanged. Never repair, regenerate, or reassign an identity in this stage.
- All rows survive a successful run. Duplicate IDs/barcodes, identity mismatches, malformed CSV/JSON, or empty required names abort publication; no silent deduplication or filtering occurs.
- `product_master_canonical.csv` is published separately from `product_master.csv`. It has 43 fields. The original source dataset and report remain available for comparison; downstream promotion to primary Product Master is a separate decision.
- Canonical rows retain the 25 Milestone 2 fields. When a source cell changes, its exact original string is stored in `source_values`; unchanged values need no redundant copy. This includes category/tag placeholders, formatting corrections, score changes, and unusable image references.
- The canonical report includes input/output SHA-256, input/image roots, source report checksum, source retrieval date, processing time, normalization version, exact columns, before/after audit counts, changed fields, and review issues. An unavailable retrieval date is explicitly null.
- `CANONICAL_VERSION` is independent of the Milestone 2 ingestion version. Increment it when changing the canonical contract or transformation rules. Determinism assumes the same input CSV and local image bytes; processing timestamps exist only in the report.

### Added fields (18)

| Field                         | Representation and purpose                                                                                                            |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `source_values`               | JSON object of changed field → exact original CSV cell                                                                                |
| `product_name_normalized`     | Case-folded NFC search name; original display casing retained in `product_name`                                                       |
| `brand_normalized`            | Sorted JSON array of conservative, case-folded brand tokens; no fuzzy/diacritic-based brand merges                                    |
| `category_normalized`         | Sorted JSON array of genuine OFF category tags; preserve namespace/hierarchy; `text:` fallback for untagged source text               |
| `country_normalized`          | Sorted JSON array of country tags, retaining all supplied countries; `text:` fallback                                                 |
| `quantity_normalized`         | Search form of quantity; simple unit/spacing normalization, no guessed conversions                                                    |
| `search_text`                 | Deterministic labeled product text for later text retrieval/embeddings                                                                |
| `missing_value_reasons`       | JSON object distinguishing absence, explicit source-unavailable/not-applicable, placeholders, and missing image states                |
| `normalization_issues`        | Sorted JSON array of cleaning changes and source-data review flags                                                                    |
| `nutrition_review_required`   | Boolean; flags high source nutrient values without rewriting them                                                                     |
| `image_available`             | Boolean; file presence observed during local inspection, even if decoding/format later fails                                          |
| `image_valid`                 | Boolean; eligible for future image processing only after local validation                                                             |
| `image_format`                | Detected format; valid set JPEG/PNG/WebP, empty if undetectable                                                                       |
| `image_width`, `image_height` | Positive pixel dimensions, nullable when unavailable                                                                                  |
| `image_size_bytes`            | Local file size, nullable when unavailable                                                                                            |
| `image_sha256`                | Checksum of inspected bounded image bytes, empty if unavailable                                                                       |
| `image_validation_status`     | `valid`, `no_path`, `unsafe_path`, `missing_file`, `unreadable`, `oversize`, `unsupported_format`, `invalid_dimensions`, or `corrupt` |

CSV is UTF-8 with JSON cells for objects/arrays and empty cells for absent optional scalars. `search_text` uses quoted multiline CSV cells; count rows with a CSV parser, not physical line counting. `image_path` remains relative to the report's image root, and is usable only when `image_valid=true`.

### Normalization decisions from the actual audit

1. Input whitespace/NFC normalization was already sound. Safely decode HTML entities in ingredients/serving text; preserve order, percentages, variants, pack size, display casing, and meaningful Unicode. Do not repair guessed OCR spelling or mojibake.
2. Case folding resolves casing-only brand/search variants. Accents and distinct spellings remain distinct; no brand alias mappings are currently justified or introduced.
3. Category missingness was overstated as completeness: 1,802 source values consisted solely of placeholders (`undefined`, `en:null`, etc.). Remove only complete placeholder tokens. Preserve every genuine category tag, including parents and multiple languages; do not infer a leaf from sorted tag order.
4. Country tags supply a consistent multi-country representation alongside display strings. Raw/source strings remain recoverable. Missing packaging remains missing; standalone `Unknown` gets no fabricated replacement.
5. Nutrition remains a compact, finite, non-negative JSON object with the existing basis/source. The audit found 632 weight-nutrient values above 100 across 435 products. Flag `over_100g_per_100g` for explicit 100g basis and `high_value_basis_review` for 100ml/ambiguous legacy bases. Preserve source values for review; do not infer serving corrections. These flagged facts require review before downstream factual claims.
6. Every referenced image is locally opened and decoded using the existing Milestone 2 image checks. Unsafe/missing/invalid usable paths are cleared with source preservation and explicit status. No image requests or repairs are made.
7. Search text uses a fixed field order: name, brand, normalized categories, ingredients, normalized countries, packaging, quantity. Empty fields are omitted. Nutrition and operational retail fields are excluded.
8. Reuse `Product.score(image_valid)` with the original seven equal presence weights. Cleaned placeholders do not count as present. The initial canonical score is 0.8679 versus 0.9537 before cleaning; this remains a completeness measure, not factual correctness.

### Validation gate

`--validate` recomputes the entire expected canonical dataset from the immutable input and current local image bytes. It checks all schema/identity rules, exact row preservation, derived text, image metadata/checksums, byte-identical CSV, and every report field except processing time. It is read-only and cannot silently regenerate either output. Focused tests are included in the existing `npm run check` pipeline. Milestone 4 remains gated by explicit project-owner confirmation.

## 17. Milestone 4 Synthetic Retail Contract

**Controlled synthetic retail operational data linked to real Open Food Facts product records.** Public product metadata lacks complete retailer-specific operational information, so this stage supplies a transparent academic simulation. It does not claim to describe real retailer stock, prices, sales, suppliers, or promotions.

Implementation: `pipelines/ingestion/retail/` in the existing offline Python package. Input: `data/processed/product_master_canonical.csv`, validated against `CanonicalProduct` and, by default, its matching checksum-bound canonical report. Output: ten relational CSVs and metadata under `data/synthetic/`, with a quality report under `data/reports/`. No real Product Master fields are overwritten and no products are generated.

### Relational CSV schema

All IDs are strings, all counts are integers, money is decimal INR (two decimal places), and dates are ISO `YYYY-MM-DD`. Executable row schemas are in `schema.py`; cross-table validation is in `validation.py`.

| Dataset                  | Columns                                                                                                     | Key / relationship                                                      |
| ------------------------ | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `stores.csv`             | `store_id`, `store_name`, `city`, `region`, `store_type`                                                    | PK `store_id`; fictional RetailVision entities                          |
| `shelves.csv`            | `shelf_id`, `store_id`, `shelf_name`, `aisle`, `category`, `capacity`                                       | PK `shelf_id`; FK store; synthetic merchandising category               |
| `placements.csv`         | `placement_id`, `product_id`, `store_id`, `shelf_id`, `facings`, `shelf_position`                           | PK `placement_id`; unique product/store; FKs Product Master/store/shelf |
| `inventory.csv`          | `inventory_id`, `placement_id`, `product_id`, `store_id`, `shelf_id`, `stock`, `reorder_level`, `max_stock` | PK `inventory_id`; unique placement; exact placement tuple match        |
| `sales.csv`              | `product_id`, `store_id`, `units_sold_7d`, `units_sold_30d`                                                 | Composite PK product/store; exactly one row per placement pair          |
| `prices.csv`             | `product_id`, `store_id`, `base_price`, `current_price`, `currency`                                         | Composite PK product/store; exactly one row per placement pair          |
| `suppliers.csv`          | `supplier_id`, `supplier_name`, `region`                                                                    | PK `supplier_id`; fictional supply entities                             |
| `product_suppliers.csv`  | `product_id`, `supplier_id`                                                                                 | PK product; exactly one primary supplier for every source product       |
| `promotions.csv`         | `promotion_id`, `promotion_name`, `promotion_type`, `discount_percentage`, `start_date`, `end_date`         | PK `promotion_id`; percentage-based campaign definitions                |
| `product_promotions.csv` | `placement_id`, `product_id`, `store_id`, `shelf_id`, `promotion_id`                                        | PK placement; zero or one campaign per placement; exact tuple match     |

Entity formats: `STORE_001`, `SHELF_001_01`, `SUP_001`, `PROMO_001`. Placement IDs are `PLC_<store_id>_<product_id>`, inventory IDs are `INV_<store_id>_<product_id>`. Names and source row numbers are never foreign keys. Product IDs are preserved verbatim as `OFF_<barcode>`.

One shelf placement per product/store makes store-scoped prices and sales unambiguous. Promotion assignments must retain store/placement context in later SQL and graph imports; a Product→Promotion graph edge must not imply a discount in every store. Supplier assignments are global primary supplier relationships, while shelves and inventory are store-specific.

### Generation rules and limits

- Defaults: 3,000 input products, 8 stores, 15 shelves per store, 6,500 placements, 30 suppliers, 200 campaigns, 15% placement assignments. Every input product appears in at least one store and has exactly one primary supplier. Default maximum coverage is four stores/product. Infeasible requested placement counts fail explicitly.
- A fixed `random.Random(seed)` operates over sorted source IDs and deterministic iteration orders. Different stores vary in assortment, demand, and prices. Explicit fixture tests verify output equality across different process hash seeds.
- `rules.py` lists exact OFF category tags, synthetic merchandising groups, category-dependent INR price ranges, and demand multipliers. Missing/unmapped tags fall back to General Grocery for shelf organization only. Canonical product categories remain untouched, including the existing 1,803 missing categories.
- Shelf groups are allocated using each store's product-profile mix. Facings occupy non-overlapping positive intervals; a shelf represents a merchandising zone with aggregate unit capacity. The sum of placement `max_stock` reservations cannot exceed that capacity.
- Stock draws from a controlled 65/24/8/3 healthy/low/critical/out-of-stock target mix. `0 <= stock <= max_stock`, `0 < reorder_level < max_stock`. Mutually exclusive report buckets separate zero stock, positive critical stock at/below one-quarter reorder, other below-reorder stock, and healthy stock. The inclusive `low_stock_count` is every row satisfying `stock < reorder_level`.
- Synthetic monthly demand uses slow/normal/fast product baselines, category factor, store factor, facings, bounded noise, and modest promotion lift. Generate the recent 7-day and prior 23-day windows separately; their sum is the 30-day total. Historical promotion overlap affects only overlapping days. Current stock is a snapshot; sales totals are not a simulated stock ledger or ML forecast.
- Base prices are product-profile-dependent with up to ±5% store variation. Price bands are assumptions, not sourced prices; package-size and import economics are not estimated. Money uses Decimal with `ROUND_HALF_UP` to two places. Current price is exactly `base_price * (1 - discount / 100)` when the assigned promotion is active, otherwise base price.
- Campaign types are `PERCENTAGE_DISCOUNT`, `CLEARANCE`, `SEASONAL`, all explicitly percentage-based. Default rates 5–25%; schema ceiling 35%. Do not interpret these as flat discounts or BOGO. Dates satisfy start < end, active bounds inclusive. Campaign mix is 70% active, 20% expired, 10% scheduled at the fixed simulation date.
- Six seeded placement identities deliberately anchor scenarios A–F. Report actual counts for high-sales/low-stock, high-sales/healthy, low-sales/high-stock, active-promotion/low-stock, active-promotion/high-sales, and out-of-stock/recent-sales. Defaults define high sales as ≥90 units/30 days, low sales as ≤15, high stock as ≥75% of maximum. Fail validation if any required scenario is absent.
- Images and nutrition, including review-flagged source values, are not used to invent retail data or exclude products. Existing canonical review rules continue to apply to later factual retrieval.

### Reproducibility, metadata and validation

Configuration uses root `.env` `SYNTHETIC_*` variables, documented in `.env.example`/README, plus CLI overrides. `SYNTHETIC_AS_OF_DATE` (default `2026-09-17`) is the simulation anchor for stock, sales windows and campaign activity. `generation_timestamp` is explicitly labeled simulation midnight UTC, not the wall-clock execution time; real execution timestamps appear only in structured logs. All ten CSVs, `metadata.json`, and `synthetic_retail_quality.json` therefore reproduce byte-for-byte for identical input bytes, seed, configuration and rule version.

Metadata includes the canonical CSV checksum, seed, configuration, `RETAIL_VERSION`, deterministic generation ID, schemas, and CSV checksums. The quality report additionally includes counts, stock/sales/promotion distributions, store/product coverage, scenario counts/examples, and referential-integrity results. Increment `RETAIL_VERSION` when changing generation or validation semantics. Output locations do not affect generated bytes.

`npm run generate:retail` generates and validates locally. `--dry-run` validates input/scale and shows settings without writes. `--validate` is read-only: it checks actual stored rows for types, primary keys, foreign keys, shelf-store and placement-tuple consistency, full inventory/sales/price coverage, primary suppliers, dates, discount math, shelf reservations, and facing overlaps. It then regenerates expected bytes in memory and compares all twelve files, detecting drift in input/configuration/rules and edited or interrupted outputs. Invalid references are reported and never silently dropped or replaced.

Files are atomically replaced individually, with manifest/report published last; this is not a multi-file database transaction. Validation detects partial output sets; repeat generation repairs them. The Product Master and prior milestone reports are protected from output-path collisions. All generated retail files are Git-ignored. Existing tests plus focused retail tests run under `npm run check`.

Milestone 5 database loading requires explicit project-owner confirmation.
