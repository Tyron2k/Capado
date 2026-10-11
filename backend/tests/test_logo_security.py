"""Real HTTP logo uploads/reads with persisted data and actual role checks."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_session
from app.models.organization_settings import OrganizationSettings
from app.models.user import User
from app.routers import settings
from app.services.auth_service import create_access_token
from tests.logo_fixtures import ACTIVE_SVG, RASTER_LOGOS


@pytest.fixture
async def logo_client(db_session):
    app = FastAPI()
    app.include_router(settings.router, prefix="/api")

    async def session():
        yield db_session

    app.dependency_overrides[get_session] = session
    users = {}
    for role in ["viewer", "editor", "admin"]:
        user = User(
            email=f"{role}@example.test",
            name=role,
            role=role,
            password_hash="",
            must_change_password=False,
        )
        db_session.add(user)
        users[role] = user
    await db_session.commit()
    headers = {
        role: {
            "Authorization": "Bearer "
            + create_access_token(
                user_id=user.id, role=role, scopes={}, email=user.email
            )
        }
        for role, user in users.items()
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://capado.example.test"
    ) as client:
        yield client, headers


@pytest.mark.parametrize("mime_type", RASTER_LOGOS)
async def test_real_raster_upload_and_public_read(logo_client, db_session, mime_type):
    client, headers = logo_client
    data = RASTER_LOGOS[mime_type]
    response = await client.post(
        "/api/settings/logo",
        files={"file": ("logo", data, mime_type)},
        headers=headers["admin"],
    )
    assert response.status_code == 204
    public = await client.get("/api/settings/logo")
    assert public.status_code == 200 and public.content == data
    assert public.headers["content-type"] == mime_type
    assert public.headers["x-content-type-options"] == "nosniff"
    assert (
        public.headers["content-security-policy"]
        == "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    )


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("viewer", 403), ("editor", 403), ("admin", 204)]
)
async def test_upload_uses_actual_role_permissions(logo_client, role, expected):
    client, headers = logo_client
    response = await client.post(
        "/api/settings/logo",
        files={"file": ("logo.png", RASTER_LOGOS["image/png"], "image/png")},
        headers=headers[role] if role else {},
    )
    assert response.status_code == expected


@pytest.mark.parametrize(
    "data,mime_type",
    [
        (ACTIVE_SVG, "image/svg+xml"),
        (ACTIVE_SVG, "image/png"),
        (b"<html><script>alert(1)</script></html>", "image/jpeg"),
        (RASTER_LOGOS["image/png"], "image/gif"),
        (b"", "image/png"),
        (b"invalid", "image/webp"),
    ],
)
async def test_rejected_upload_preserves_existing_logo(
    logo_client, db_session, data, mime_type
):
    client, headers = logo_client
    original = OrganizationSettings(
        logo_data=RASTER_LOGOS["image/png"], logo_mime_type="image/png"
    )
    db_session.add(original)
    await db_session.commit()
    response = await client.post(
        "/api/settings/logo",
        files={"file": ("logo", data, mime_type)},
        headers=headers["admin"],
    )
    assert response.status_code == 400
    await db_session.refresh(original)
    assert (
        original.logo_data == RASTER_LOGOS["image/png"]
        and original.logo_mime_type == "image/png"
    )


async def test_size_limit_rejects_before_storage(logo_client, db_session):
    client, headers = logo_client
    data = RASTER_LOGOS["image/png"] + b"x" * settings.MAX_LOGO_SIZE
    response = await client.post(
        "/api/settings/logo",
        files={"file": ("logo.png", data, "image/png")},
        headers=headers["admin"],
    )
    assert response.status_code == 400


async def test_legacy_svg_is_preserved_but_only_served_sandboxed(
    logo_client, db_session
):
    client, _ = logo_client
    original = OrganizationSettings(
        logo_data=ACTIVE_SVG, logo_mime_type="image/svg+xml"
    )
    db_session.add(original)
    await db_session.commit()
    response = await client.get("/api/settings/logo")
    assert response.status_code == 200 and response.content == ACTIVE_SVG
    assert response.headers["content-type"] == "image/svg+xml"
    assert (
        response.headers["content-security-policy"]
        == "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    await db_session.refresh(original)
    assert (
        original.logo_data == ACTIVE_SVG and original.logo_mime_type == "image/svg+xml"
    )


@pytest.mark.parametrize("mime_type", ["text/html", "image/png", "image/webp"])
async def test_unsafe_legacy_mime_or_content_cannot_be_served(
    logo_client, db_session, mime_type
):
    client, _ = logo_client
    original = OrganizationSettings(logo_data=ACTIVE_SVG, logo_mime_type=mime_type)
    db_session.add(original)
    await db_session.commit()
    response = await client.get("/api/settings/logo")
    assert response.status_code == 404
    await db_session.refresh(original)
    assert original.logo_data == ACTIVE_SVG
