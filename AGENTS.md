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

- Milestone 1 foundation is the only implemented scope.
- Frontend checks the Express health endpoint.
- Express checks its own health and can check FastAPI health.
- AI, databases, ingestion, retrieval, vision, OCR, and LLM reasoning are not implemented.
- Do not begin Milestone 2 without explicit user confirmation.

## Repository Map

- `frontend/`: browser application.
- `backend/`: API and future evidence orchestration.
- `ai-service/`: Python model/inference boundary.
- `docs/openapi.yaml`: current backend API contract.
- `PROJECT_SPEC.md`: architecture, boundaries, data rules, and milestone plan.

## Engineering Rules

- Keep secrets in environment variables; never commit `.env`.
- Preserve PostgreSQL, Neo4j, Qdrant, Gemini Embedding 2, OpenAI, YOLO, and PaddleOCR choices unless the user approves a change.
- Deterministic code computes stock conditions and analytics; the LLM explains retrieved evidence and must not invent facts.
- Add only milestone-relevant folders and dependencies.
- Run `npm run check` before declaring a milestone complete.
