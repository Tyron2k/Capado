"""Unit tests for tenant settings (service + router).

Pure unit tests without a database — a mocked AsyncSession verifies the
singleton get-or-create logic (including concurrent-insert recovery), the
partial-update semantics, and logo store/clear behaviour. Router-level tests
cover the logo-upload validation (MIME type, size limit) and the logo-serving
404 path, plus the has_uploaded_logo response proxy.
"""

import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers, UploadFile

from app.models.organization_settings import OrganizationSettings
from app.routers.settings import (
    MAX_LOGO_SIZE,
    _to_response,
    get_logo,
    upload_logo,
)
from app.services.settings_service import (
    _get_or_create_settings,
    delete_logo,
    save_logo,
    update_organization_settings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(exec_results: list) -> AsyncMock:
    """Build a mocked AsyncSession.

    Specced against the real ``sqlalchemy.ext.asyncio.AsyncSession`` so the mock
    only exposes attributes the real session has. This guards against using the
    SQLModel-only ``.exec()`` API (the real async session has ``.execute()``).

    Args:
        exec_results: One value per expected ``session.execute`` call. Each
            value is what ``.scalars().first()`` should return for that call.

    Returns:
        An AsyncMock session whose ``execute`` yields result objects in order.
    """
    session = AsyncMock(spec=AsyncSession)

    def _make_result(value):
        result = MagicMock()
        scalars = MagicMock()
        scalars.first = MagicMock(return_value=value)
        result.scalars = MagicMock(return_value=scalars)
        return result

    session.execute = AsyncMock(side_effect=[_make_result(v) for v in exec_results])
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


def _upload_file(content: bytes, content_type: str) -> UploadFile:
    """Create a Starlette UploadFile with the given bytes and content type."""
    return UploadFile(
        filename="logo",
        file=io.BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


# ---------------------------------------------------------------------------
# _get_or_create_settings — singleton behaviour
# ---------------------------------------------------------------------------


class TestGetOrCreateSettings:
    """Tests for the singleton get-or-create helper."""

    async def test_returns_existing_row(self):
        """An existing settings row is returned without creating a new one."""
        existing = OrganizationSettings(company_name="Existing Corp")
        session = _make_session([existing])

        result = await _get_or_create_settings(session)

        assert result is existing
        session.add.assert_not_called()
        session.commit.assert_not_called()

    async def test_creates_row_when_absent(self):
        """When no row exists, a default row is created and committed."""
        session = _make_session([None])

        result = await _get_or_create_settings(session)

        assert isinstance(result, OrganizationSettings)
        assert result.company_name == "Capado"
        assert result.singleton_key == "default"
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    async def test_recovers_from_concurrent_insert(self):
        """A concurrent insert (IntegrityError) is recovered by re-selecting."""
        winner = OrganizationSettings(company_name="Winner Corp")
        # First exec: no row. Second exec (after rollback): the winner's row.
        session = _make_session([None, winner])
        session.commit = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("duplicate key"))
        )

        result = await _get_or_create_settings(session)

        assert result is winner
        session.rollback.assert_awaited_once()
        assert session.execute.await_count == 2

    async def test_reraises_when_recovery_finds_nothing(self):
        """If the row is still missing after IntegrityError, the error propagates."""
        session = _make_session([None, None])
        session.commit = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("duplicate key"))
        )

        with pytest.raises(IntegrityError):
            await _get_or_create_settings(session)

        session.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# update_organization_settings — partial update semantics
# ---------------------------------------------------------------------------


class TestUpdateOrganizationSettings:
    """Tests for partial branding updates."""

    async def test_updates_only_provided_fields(self):
        """Only non-None fields are changed; others keep their values."""
        existing = OrganizationSettings(
            company_name="Old Name",
            company_subtitle="Old Subtitle",
            primary_color="blue",
        )
        session = _make_session([existing])

        result = await update_organization_settings(
            session, company_name="New Name", primary_color="#123456"
        )

        assert result.company_name == "New Name"
        assert result.primary_color == "#123456"
        # Untouched field retains its previous value.
        assert result.company_subtitle == "Old Subtitle"
        session.commit.assert_awaited_once()

    async def test_none_values_are_ignored(self):
        """Passing all None leaves branding fields unchanged."""
        existing = OrganizationSettings(company_name="Keep Me")
        session = _make_session([existing])

        result = await update_organization_settings(session)

        assert result.company_name == "Keep Me"


# ---------------------------------------------------------------------------
# save_logo / delete_logo
# ---------------------------------------------------------------------------


class TestLogoStorage:
    """Tests for storing and clearing the logo blob."""

    async def test_save_logo_sets_data_and_mime(self):
        """save_logo stores the binary content and its MIME type."""
        existing = OrganizationSettings()
        session = _make_session([existing])

        result = await save_logo(session, data=b"imgbytes", mime_type="image/png")

        assert result.logo_data == b"imgbytes"
        assert result.logo_mime_type == "image/png"
        session.commit.assert_awaited_once()

    async def test_delete_logo_clears_data_and_mime(self):
        """delete_logo resets both logo fields to None."""
        existing = OrganizationSettings(
            logo_data=b"imgbytes", logo_mime_type="image/png"
        )
        session = _make_session([existing])

        result = await delete_logo(session)

        assert result.logo_data is None
        assert result.logo_mime_type is None
        session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# _to_response — has_uploaded_logo proxy
# ---------------------------------------------------------------------------


class TestToResponse:
    """Tests for the response mapping that avoids loading the blob."""

    def test_has_uploaded_logo_true_when_mime_present(self):
        """has_uploaded_logo is True when logo_mime_type is set."""
        settings = OrganizationSettings(logo_mime_type="image/png")
        response = _to_response(settings)
        assert response.has_uploaded_logo is True

    def test_has_uploaded_logo_false_when_mime_absent(self):
        """has_uploaded_logo is False when no logo MIME type is stored."""
        settings = OrganizationSettings(logo_mime_type=None)
        response = _to_response(settings)
        assert response.has_uploaded_logo is False


# ---------------------------------------------------------------------------
# upload_logo router — validation
# ---------------------------------------------------------------------------


class TestUploadLogoValidation:
    """Tests for logo-upload MIME and size validation."""

    async def test_rejects_unsupported_mime_type(self):
        """A non-image MIME type is rejected with 400 and save is not called."""
        session = AsyncMock()
        file = _upload_file(b"data", "application/pdf")

        with pytest.raises(HTTPException) as exc_info:
            await upload_logo(file=file, session=session, current_user=MagicMock())

        assert exc_info.value.status_code == 400

    async def test_rejects_oversized_file(self):
        """A file exceeding MAX_LOGO_SIZE is rejected with 400."""
        session = AsyncMock()
        oversized = b"x" * (MAX_LOGO_SIZE + 1)
        file = _upload_file(oversized, "image/png")

        with pytest.raises(HTTPException) as exc_info:
            await upload_logo(file=file, session=session, current_user=MagicMock())

        assert exc_info.value.status_code == 400

    async def test_accepts_valid_image(self, monkeypatch):
        """A valid, in-limit image is passed to save_logo."""
        saved = {}

        async def _fake_save_logo(session, *, data, mime_type):
            saved["data"] = data
            saved["mime_type"] = mime_type

        monkeypatch.setattr("app.routers.settings.save_logo", _fake_save_logo)

        session = AsyncMock()
        file = _upload_file(b"pngbytes", "image/png")

        await upload_logo(file=file, session=session, current_user=MagicMock())

        assert saved["data"] == b"pngbytes"
        assert saved["mime_type"] == "image/png"


# ---------------------------------------------------------------------------
# get_logo router — serving and 404
# ---------------------------------------------------------------------------


class TestGetLogo:
    """Tests for serving the uploaded logo binary."""

    async def test_returns_404_when_no_logo(self, monkeypatch):
        """When no logo is stored, the endpoint returns 404."""

        async def _fake_get_with_logo(session):
            return OrganizationSettings(logo_data=None, logo_mime_type=None)

        monkeypatch.setattr(
            "app.routers.settings.get_organization_settings_with_logo",
            _fake_get_with_logo,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_logo(session=AsyncMock())

        assert exc_info.value.status_code == 404

    async def test_serves_logo_bytes(self, monkeypatch):
        """When a logo is stored, its bytes and MIME type are returned."""

        async def _fake_get_with_logo(session):
            return OrganizationSettings(
                logo_data=b"pngbytes", logo_mime_type="image/png"
            )

        monkeypatch.setattr(
            "app.routers.settings.get_organization_settings_with_logo",
            _fake_get_with_logo,
        )

        response = await get_logo(session=AsyncMock())

        assert response.body == b"pngbytes"
        assert response.media_type == "image/png"
