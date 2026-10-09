"""HTTP permissions, size bounds and response semantics of complete CSV migration."""

import io

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient

from app.database import get_session
from app.models.user import User
from app.routers.import_export import import_migration_endpoint, router
from app.services.permissions import get_current_user


@pytest.mark.parametrize("role", ["viewer", "editor", None])
@pytest.mark.parametrize(
    "method,path", [("GET", "/api/migration/export"), ("POST", "/api/migration/import")]
)
async def test_migration_is_admin_only(db_session, role, method, path):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def current_user():
        if role is None:
            raise HTTPException(401, "Authentication required")
        return User(
            email="test@example.test", name="Test", password_hash="unused", role=role
        )

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_session] = lambda: db_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            path,
            files={"file": ("capado-csv.zip", b"invalid")}
            if method == "POST"
            else None,
        )
    assert response.status_code == (401 if role is None else 403)


async def test_zip_upload_is_bounded_before_parsing(monkeypatch, db_session):
    from app.services.import_export import csv_transfer as migration

    monkeypatch.setattr(migration, "MAX_ARCHIVE_BYTES", 5)
    upload = UploadFile(filename="data.zip", file=io.BytesIO(b"123456789"))
    admin = User(
        email="admin@example.test", name="Admin", password_hash="unused", role="admin"
    )
    with pytest.raises(HTTPException) as error:
        await import_migration_endpoint(upload, db_session, admin)
    assert error.value.status_code == 413
    assert upload.file.tell() == 6


async def test_invalid_zip_reports_no_partial_success(db_session):
    admin = User(
        email="admin@example.test", name="Admin", password_hash="unused", role="admin"
    )
    response = await import_migration_endpoint(
        UploadFile(filename="data.zip", file=io.BytesIO(b"not a zip")),
        db_session,
        admin,
    )
    assert response.created == response.updated == 0
    assert response.errors and not response.success


async def test_admin_can_download_and_restore_package_through_http(db_session):
    from app.services.import_export.csv_transfer import parse_migration

    admin = User(
        email="admin@example.test",
        name="Admin",
        password_hash="retained",
        role="admin",
        must_change_password=False,
    )
    db_session.add(admin)
    await db_session.commit()
    admin_id = admin.id
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_session] = lambda: db_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        download = await client.get("/api/migration/export")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/zip"
        assert "capado-csv.zip" in download.headers["content-disposition"]
        assert parse_migration(download.content)["users"][0]["id"] == admin_id
        restored = await client.post(
            "/api/migration/import",
            files={"file": ("capado-csv.zip", download.content, "application/zip")},
        )
        assert restored.status_code == 200
        assert restored.json()["success"] and restored.json()["errors"] == []
        assert restored.json()["updated"] == 1


@pytest.mark.parametrize("role", ["viewer", "editor", None])
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/data/administration/export"),
        ("GET", "/api/data/history/export"),
        ("POST", "/api/data/skills/import"),
        ("POST", "/api/data/personnel/import"),
        ("POST", "/api/personnel/import"),
    ],
)
async def test_sensitive_area_exports_and_all_area_imports_require_admin(
    db_session, role, method, path
):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def current_user():
        if role is None:
            raise HTTPException(401, "Authentication required")
        return User(
            email="test@example.test", name="Test", password_hash="unused", role=role
        )

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_session] = lambda: db_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            path,
            files={"file": ("data.csv", b"invalid")} if method == "POST" else None,
        )
    assert response.status_code == (401 if role is None else 403)


async def test_original_page_routes_download_the_exact_zip_csvs_and_accept_atomic_updates(
    db_session,
):
    from zipfile import ZipFile

    from sqlalchemy import select

    from app.models.resource import PersonalResource
    from app.models.resource_group import ResourceGroup
    from app.services.import_export import AREAS
    from app.services.import_export import csv_transfer as migration

    admin = User(
        email="admin@example.test", name="Admin", password_hash="retained", role="admin"
    )
    group = ResourceGroup(name="Empty team", resource_type="personal")
    db_session.add_all([admin, group])
    await db_session.flush()
    person = PersonalResource(name="Inactive", group_id=group.id, is_active=False)
    db_session.add(person)
    await db_session.commit()
    person_id = person.id
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_session] = lambda: db_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        package = await client.get("/api/migration/export")
        with ZipFile(io.BytesIO(package.content)) as zipped:
            for area in AREAS:
                path = (
                    f"/api/{area.name}/export"
                    if area.name
                    in {
                        "personnel",
                        "infrastructure",
                        "projects",
                        "templates",
                        "assignments",
                    }
                    else f"/api/data/{area.name}/export"
                )
                response = await client.get(path, params={"format": "csv"})
                assert response.status_code == 200, area.name
                assert response.content == zipped.read(area.name + ".csv"), area.name
                assert area.name + ".csv" in response.headers["content-disposition"]
            content = zipped.read("personnel.csv").replace(
                b"Inactive", b"Updated inactive"
            )
        imported = await client.post(
            "/api/personnel/import",
            files={"file": ("personnel.csv", content, "text/csv")},
        )
        assert imported.json()["success"] and imported.json()["atomic"]
        restored = (
            await db_session.execute(
                select(PersonalResource).where(PersonalResource.id == person_id)
            )
        ).scalar_one()
        await db_session.refresh(restored)
        assert restored.name == "Updated inactive" and not restored.is_active
        rejected = await client.post(
            "/api/personnel/import",
            files={
                "file": (
                    "personnel.csv",
                    content.replace(
                        b"Capado CSV;2;personnel", b"Capado CSV;2;projects"
                    ),
                    "text/csv",
                )
            },
        )
        assert not rejected.json()["success"] and rejected.json()["atomic"]
        assert rejected.json()["created"] == rejected.json()["updated"] == 0
        await db_session.refresh(restored)
        assert restored.name == "Updated inactive"
        unknown = await client.get("/api/data/not-an-area/export")
        assert unknown.status_code == 404
