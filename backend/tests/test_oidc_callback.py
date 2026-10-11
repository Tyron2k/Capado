"""HTTP regressions for the OIDC cookie handoff, with a synthetic provider."""

import logging
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.database import get_session
from app.models.user import RefreshToken, User
from app.routers import auth, oidc
from app.services.auth_service import decode_access_token
from app.services.oidc_service import OIDCUserInfo
from app.utils.logging import AuthQueryFilter


@pytest.fixture
async def oidc_client(db_session, monkeypatch):
    user = User(
        email="oidc@example.test",
        name="OIDC Test User",
        password_hash="",
        role="editor",
        external_id="test-subject",
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.commit()
    monkeypatch.setattr(oidc, "OIDC_ENABLED", True)
    monkeypatch.setattr(oidc, "FRONTEND_URL", "https://capado.example.test")
    monkeypatch.setattr(
        oidc,
        "exchange_code_for_tokens",
        AsyncMock(return_value={"access_token": "provider-token"}),
    )
    monkeypatch.setattr(
        oidc,
        "get_userinfo",
        AsyncMock(
            return_value=OIDCUserInfo(
                sub="test-subject",
                email=user.email,
                name=user.name,
                email_verified=True,
            )
        ),
    )
    app = FastAPI()
    app.include_router(oidc.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")

    async def session():
        yield db_session

    app.dependency_overrides[get_session] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://capado.example.test"
    ) as client:
        client.cookies.set("oidc_state", oidc._sign_state("test-state"))
        yield client


def assert_safe_redirect(response):
    location = response.headers["location"]
    assert not re.search(
        r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", urlsplit(location).query
    )
    assert not urlsplit(location).fragment
    assert "access_token" not in location
    assert "refresh_token" not in location


@pytest.mark.parametrize("secure", [False, True])
async def test_callback_cookie_handoff_rotation_and_logout(
    oidc_client, db_session, monkeypatch, secure
):
    monkeypatch.setattr(settings, "cookie_secure", secure)
    response = await oidc_client.get(
        "/api/auth/oidc/callback", params={"code": "test-code", "state": "test-state"}
    )
    assert response.status_code == 302
    assert_safe_redirect(response)
    assert (
        response.headers["location"] == "https://capado.example.test/auth/oidc/callback"
    )
    cookie = response.headers["set-cookie"]
    assert (
        "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/auth" in cookie
    )
    assert ("Secure" in cookie) == secure
    initial = oidc_client.cookies.get(settings.refresh_cookie_name)
    refreshed = await oidc_client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert "refresh_token" not in refreshed.json()
    claims = decode_access_token(refreshed.json()["access_token"])
    assert claims["email"] == "oidc@example.test"
    rotated = oidc_client.cookies.get(settings.refresh_cookie_name)
    assert rotated != initial
    old = await db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == sha256(initial.encode()).hexdigest()
        )
    )
    assert old.revoked_at is not None and old.replaced_by_id is not None
    assert (await oidc_client.post("/api/auth/refresh")).status_code == 200
    assert (await oidc_client.post("/api/auth/logout")).status_code == 204
    assert (await oidc_client.post("/api/auth/refresh")).status_code == 401


async def test_invalid_state_and_missing_cookie(oidc_client):
    assert (
        await oidc_client.get(
            "/api/auth/oidc/callback", params={"state": "wrong", "code": "test"}
        )
    ).status_code == 400
    oidc_client.cookies.clear()
    assert (
        await oidc_client.get(
            "/api/auth/oidc/callback", params={"state": "test-state", "code": "test"}
        )
    ).status_code == 400
    assert (await oidc_client.post("/api/auth/refresh")).status_code == 401


async def test_expired_refresh_is_rejected(oidc_client, db_session):
    await oidc_client.get(
        "/api/auth/oidc/callback", params={"code": "test-code", "state": "test-state"}
    )
    token = await db_session.scalar(select(RefreshToken))
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert (await oidc_client.post("/api/auth/refresh")).status_code == 401


@pytest.mark.parametrize("stage", ["provider", "exchange", "userinfo"])
async def test_provider_failures_never_echo_credentials(
    oidc_client, monkeypatch, caplog, stage
):
    secret = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzeW50aGV0aWMifQ.test-signature"
    params = {"code": "test-code", "state": "test-state"}
    if stage == "provider":
        params.update(error=secret, error_description=secret + "\r\nforged log")
    else:
        method = "exchange_code_for_tokens" if stage == "exchange" else "get_userinfo"
        monkeypatch.setattr(oidc, method, AsyncMock(side_effect=RuntimeError(secret)))
    response = await oidc_client.get("/api/auth/oidc/callback", params=params)
    assert response.status_code == 302
    assert_safe_redirect(response)
    assert secret not in response.headers["location"]
    assert all(secret not in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/oidc/callback?error=secret.jwt.value",
        "/api/auth/refresh?refresh_token=secret",
    ],
)
def test_uvicorn_auth_access_logs_omit_query_credentials(path):
    # This is the actual argument layout used by both Uvicorn HTTP protocols.
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", path, "1.1", 302),
        None,
    )
    assert AuthQueryFilter().filter(record)
    assert (
        record.getMessage()
        == f'127.0.0.1:1234 - "GET {path.partition("?")[0]} HTTP/1.1" 302'
    )
    assert "secret" not in record.getMessage()
