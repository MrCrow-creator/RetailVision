# RetailVision

RetailVision is a college-scale but technically rigorous **Retail Multimodal Knowledge Intelligence Platform**. It is an implementation/adaptation inspired by the mKG-RAG paper, not a full paper reproduction.

The target system identifies products from shelf imagery and combines semantic retrieval, knowledge-graph relationships, and exact retail records before an LLM produces a grounded explanation.

## Current Scope

Milestone 1 establishes the application foundation only:

- React, TypeScript, Vite, and Tailwind CSS frontend
- Express and TypeScript orchestration API
- FastAPI AI-service boundary
- Health checks and frontend-to-backend connectivity
- Shared environment contract
- Linting, formatting, tests, and API documentation

Dataset ingestion, databases, embeddings, YOLO, OCR, retrieval, and LLM calls are intentionally **not implemented yet**.

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
Copy-Item .env.example .env
npm install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".\ai-service[dev]"
```

Keep real API keys only in `.env`. No key is required for Milestone 1.

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

`npm run check` runs the complete Milestone 1 verification sequence.

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
|-- docs/              API documentation
|-- .env.example       Environment variable template
|-- AGENTS.md          Concise context for future engineering sessions
|-- PROJECT_SPEC.md    Architecture and implementation contract
`-- package.json       npm workspace and root commands
```

Data, model, and pipeline directories will be added only when their milestones begin, avoiding empty or misleading structure.

## Next Milestone

Milestone 2 is Open Food Facts ingestion. It must not begin until the project owner confirms the Milestone 1 foundation.
