# RetailVision Agent Context

Read this file first in a new session. Use `PROJECT_SPEC.md` for the full architecture and `README.md` for setup commands.

## Project Identity

RetailVision is a final-year BE AI and Data Science implementation/adaptation inspired by mKG-RAG. It is a retail multimodal knowledge intelligence platform, not a paper reproduction, generic chatbot, simple RAG demo, or CRUD dashboard.

## Locked Architecture

- Frontend: React + TypeScript + Vite + Tailwind CSS.
- Orchestration API: Node.js + Express + TypeScript.
- AI boundary: Python + FastAPI; later owns YOLO, PaddleOCR, and embedding workflows.
- Exact operational data: PostgreSQL.
- Relationships and graph traversal: Neo4j.
- Semantic and multimodal vectors: Qdrant.
- Primary embeddings: Google Gemini Embedding 2, configurable dimension (initially 1536).
- Grounded answer generation: OpenAI, using fused evidence only.
- Stable product key everywhere: `OFF_<barcode>`. Never invent independent product IDs.

## Current State

- Milestones 1–4 (foundation, ingestion, canonicalization, synthetic retail data) are implemented.
- Frontend checks the Express health endpoint.
- Express checks its own health and can check FastAPI health.
- `npm run ingest:off` creates a bounded OFF raw snapshot, canonical CSV, images, and quality report.
- AI, databases, retrieval, vision, OCR, and LLM reasoning are not implemented.
- `npm run normalize:products` produces a separate canonical CSV, image metadata, search text, and review flags.
- `npm run generate:retail` generates seeded, validated retail CSVs linked to canonical products.
- Do not begin Milestone 5 without explicit user confirmation.

## Repository Map

- `frontend/`: browser application.
- `backend/`: API and future evidence orchestration.
- `ai-service/`: Python model/inference boundary.
- `pipelines/ingestion/openfoodfacts/`: offline CLI, schema, normalization, and resumable downloads.
- `pipelines/ingestion/canonicalization/`: local Milestone 3 transformation and validation.
- `pipelines/ingestion/retail/`: Milestone 4 synthetic generation, schemas and relational validation.
- `data/synthetic/`: generated retail CSVs and deterministic metadata (Git-ignored).
- `data/processed/product_master.csv`: canonical product dataset (generated, Git-ignored).
- `data/processed/product_master_canonical.csv`: separately validated Milestone 3 candidate dataset.
- `data/reports/openfoodfacts_quality.json`: measured quality and provenance (generated).
- `docs/openapi.yaml`: current backend API contract.
- `PROJECT_SPEC.md`: architecture, boundaries, data rules, and milestone plan.

## Engineering Rules

- Keep secrets in environment variables; never commit `.env`.
- Preserve PostgreSQL, Neo4j, Qdrant, Gemini Embedding 2, OpenAI, YOLO, and PaddleOCR choices unless the user approves a change.
- Deterministic code computes stock conditions and analytics; the LLM explains retrieved evidence and must not invent facts.
- Add only milestone-relevant folders and dependencies.
- Run `npm run check` before declaring a milestone complete.
- OFF codes follow official leading-zero normalization. Image-folder padding is separate from product identity. GS1 checksum is a reported diagnostic, not the ID rule.
- Raw snapshots are immutable. Bump `PIPELINE_VERSION` when changing normalization/schema so cached products cannot silently survive changed rules. Later pipelines consume Product Master references, not every cached image in the raw directory.
- Milestone 3 preserves input IDs verbatim and never overwrites Milestone 2 data. Version canonical rules with `CANONICAL_VERSION`. Later consumers must honor `image_valid` and `nutrition_review_required`; the completeness score is not an accuracy guarantee, and sorted category tags do not imply a leaf hierarchy.
- Retail data is explicitly synthetic; never write operational values back into Product Master. Promotions are placement/store-scoped, and inventory must match the exact placement tuple. Reproduce using seed + fixed simulation date + input checksum; version rule changes with `RETAIL_VERSION`. Metadata timestamps are labeled simulation time; wall-clock execution times are logged only.
