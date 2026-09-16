from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Health"])


class CapabilityStatus(BaseModel):
    object_detection: Literal["not_implemented"] = "not_implemented"
    ocr: Literal["not_implemented"] = "not_implemented"
    embeddings: Literal["not_implemented"] = "not_implemented"
    retrieval: Literal["not_implemented"] = "not_implemented"


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["ai-service"] = "ai-service"
    version: str
    timestamp: datetime
    capabilities: CapabilityStatus


@router.get("/health", response_model=HealthResponse, summary="Check the AI service process")
async def health() -> HealthResponse:
    return HealthResponse(
        version="0.1.0",
        timestamp=datetime.now(UTC),
        capabilities=CapabilityStatus(),
    )
