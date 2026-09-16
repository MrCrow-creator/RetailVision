import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app.main import create_app


async def get(path: str) -> Response:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_health_contract_marks_future_capabilities_not_implemented() -> None:
    response = asyncio.run(get("/health"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "ai-service"
    assert payload["version"] == "0.1.0"
    assert payload["capabilities"] == {
        "object_detection": "not_implemented",
        "ocr": "not_implemented",
        "embeddings": "not_implemented",
        "retrieval": "not_implemented",
    }


def test_openapi_document_is_available() -> None:
    response = asyncio.run(get("/openapi.json"))

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "RetailVision AI Service"
