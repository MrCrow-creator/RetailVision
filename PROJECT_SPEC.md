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
2. Open Food Facts ingestion
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
