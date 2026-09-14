"""
Tests for the backend base structure: health check and exception handlers.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from app.exceptions import (
    BusinessRuleError,
    CatchAllExceptionMiddleware,
    NotFoundError,
    register_exception_handlers,
)


def create_test_app() -> FastAPI:
    """Create a test app with exception handlers and test routes."""
    test_app = FastAPI(debug=False)

    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    test_app.add_middleware(CatchAllExceptionMiddleware)

    register_exception_handlers(test_app)

    @test_app.get("/api/health")
    async def health_check():
        return {"status": "ok"}

    @test_app.get("/test-business-error")
    async def trigger_business_error():
        raise BusinessRuleError(
            message="The field 'Name' must not be empty.",
            field="name",
        )

    @test_app.get("/test-business-error-no-field")
    async def trigger_business_error_no_field():
        raise BusinessRuleError(message="Invalid input.")

    @test_app.get("/test-not-found")
    async def trigger_not_found():
        raise NotFoundError(entity="Resource", entity_id="abc-123")

    @test_app.get("/test-not-found-no-id")
    async def trigger_not_found_no_id():
        raise NotFoundError(entity="Project")

    @test_app.get("/test-server-error")
    async def trigger_server_error():
        raise ValueError("Unexpected internal error")

    return test_app


@pytest_asyncio.fixture
async def client():
    """Test client with isolated test app."""
    test_app = create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_check(client):
    """Health check endpoint returns status ok."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_business_rule_error_returns_400(client):
    """BusinessRuleError returns HTTP 400 with error message."""
    response = await client.get("/test-business-error")
    assert response.status_code == 400
    data = response.json()
    assert data["detail"] == "The field 'Name' must not be empty."
    assert data["field"] == "name"


@pytest.mark.asyncio
async def test_business_rule_error_without_field(client):
    """BusinessRuleError without field returns only the message."""
    response = await client.get("/test-business-error-no-field")
    assert response.status_code == 400
    data = response.json()
    assert data["detail"] == "Invalid input."
    assert "field" not in data


@pytest.mark.asyncio
async def test_not_found_error_returns_404(client):
    """NotFoundError returns HTTP 404 with error message."""
    response = await client.get("/test-not-found")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"] == "Resource with ID 'abc-123' not found."


@pytest.mark.asyncio
async def test_not_found_error_without_id(client):
    """NotFoundError without ID returns generic message."""
    response = await client.get("/test-not-found-no-id")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"] == "Project not found."


@pytest.mark.asyncio
async def test_unhandled_exception_returns_500(client):
    """Unhandled errors return HTTP 500 with generic message."""
    response = await client.get("/test-server-error")
    assert response.status_code == 500
    data = response.json()
    assert data["detail"] == "An unexpected server error occurred."
