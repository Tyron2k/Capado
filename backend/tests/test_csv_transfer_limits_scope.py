"""CSV boundary symmetry, actionable diagnostics and scoped import work."""

import copy
import io
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func
from sqlmodel import select

from app import models as m
from app.database import get_session
from app.routers.import_export import router
from app.services.import_export import DOMAIN_BY_NAME, csv_format, csv_storage
from app.services.import_export import csv_transfer as transfer
from app.services.permissions import get_current_user
from tests.test_csv_migration import source


@pytest.mark.parametrize("character", ["x", "é"])
def test_export_and_import_share_utf8_field_boundaries(monkeypatch, character):
    monkeypatch.setattr(csv_format, "MAX_FIELD_BYTES", 64)
    count = 64 // len(character.encode("utf-8"))
    record = m.Skill(name=character * count, resource_type="personal").model_dump()
    data = {"skills": [record], "skill_attributes": []}
    domain = DOMAIN_BY_NAME["skills"]
    content = domain.export_csv(data)
    assert (
        domain.parse_csv(csv_format._read_csv(content)).data["skills"][0]["name"]
        == record["name"]
    )
    record["name"] += character
    with pytest.raises(ValueError, match=r"skills.csv, row 3, field name:.*4 MiB"):
        domain.export_csv(data)
    text = content.decode("utf-8-sig").replace(
        character * count, character * (count + 1)
    )
    with pytest.raises(ValueError, match=r"skills.csv, row 3, field name:.*4 MiB"):
        csv_format._read_csv(text.encode("utf-8-sig"), "skills.csv")
    # Parsed rows supplied directly to the service have the same guard.
    rows = csv_format._read_csv(content)
    rows[2][rows[1].index("name")] = character * (count + 1)
    with pytest.raises(ValueError, match="field name"):
        domain.parse_csv(rows)


async def test_oversized_history_is_rejected_at_both_download_routes(db_session):
    admin = m.User(
        email="limits@example.test", name="Admin", role="admin", password_hash="unused"
    )
    baseline = m.Baseline(name="Large historical field")
    db_session.add_all([admin, baseline])
    await db_session.flush()
    entry = m.BaselineEntry(
        baseline_id=baseline.id,
        entity_type="projects",
        entity_id=uuid4(),
        payload={"note": "x" * (csv_format.MAX_FIELD_BYTES + 1)},
    )
    db_session.add(entry)
    await db_session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for route in ("/api/data/history/export", "/api/migration/export"):
            response = await client.get(route)
            assert response.status_code == 413
            detail = response.json()["detail"]
            assert (
                "history.csv" in detail
                and "row 4" in detail
                and "field payload" in detail
            )
            assert "4 MiB" in detail
    assert (await db_session.get(m.BaselineEntry, entry.id)).payload == entry.payload


async def test_large_unrelated_history_does_not_block_small_skill_import(
    db_session, monkeypatch
):
    # A small configurable boundary makes the regression cheap: the database
    # exceeds it, the actual file does not. Existing rows must not count as uploads.
    monkeypatch.setattr(csv_format, "MAX_ROWS", 3)
    monkeypatch.setattr(csv_storage, "MAX_ROWS", 3)
    db_session.add_all(
        [
            m.Skill(name=f"Existing {index}", resource_type="personal")
            for index in range(8)
        ]
    )
    db_session.add_all(
        [
            m.AuditLog(entity_type="projects", entity_id=uuid4(), action="created")
            for _ in range(8)
        ]
    )
    await db_session.commit()
    record = m.Skill(name="New skill", resource_type="personal").model_dump()
    content = DOMAIN_BY_NAME["skills"].export_csv(
        {"skills": [record], "skill_attributes": []}
    )
    statements = []
    engine = db_session.bind.sync_engine

    def capture(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.import_export.common.refresh_resources", refresh)
    try:
        result = await transfer.import_area_rows(
            db_session, "skills", csv_format._read_csv(content)
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert not result.errors and result.created == 1
    assert not any(
        statement.startswith("select")
        and any(
            name in statement
            for name in (
                "audit_log",
                "baseline",
                "assignments",
                "personal_resources",
                "users",
            )
        )
        for statement in statements
    )
    refresh.assert_not_awaited()
    assert (
        await db_session.execute(select(func.count()).select_from(m.AuditLog))
    ).scalar_one() == 9


async def test_skill_attribute_edit_validates_existing_external_requirements(
    db_session, source
):
    requirement = (
        (await db_session.execute(select(m.WorkPackageRequirement))).scalars().first()
    )
    attribute = await db_session.get(m.SkillAttribute, requirement.skill_attribute_id)
    old_skill_id = attribute.skill_id
    other_skill = (
        (await db_session.execute(select(m.Skill).where(m.Skill.id != old_skill_id)))
        .scalars()
        .first()
    )
    record = attribute.model_dump()
    record["skill_id"] = other_skill.id
    content = DOMAIN_BY_NAME["skills"].export_csv(
        {"skills": [], "skill_attributes": [record]}
    )
    result = await transfer.import_area_rows(
        db_session, "skills", csv_format._read_csv(content), source["admin"]
    )
    assert "Requirement skill/attribute mismatch" in result.errors[0]
    assert "field skill_attribute_id" in result.errors[0]
    assert (
        "record" in result.errors[0]
    )  # Related destination record is outside this file.
    attribute = await db_session.get(m.SkillAttribute, record["id"])
    assert attribute.skill_id == old_skill_id


async def test_moved_assignment_refreshes_only_old_and_new_resources(
    db_session, source, monkeypatch
):
    resource = m.PersonalResource(
        name="New booking target",
        group_id=(await db_session.get(m.PersonalResource, source["person"])).group_id,
    )
    db_session.add(resource)
    await db_session.commit()
    assignment = (
        (
            await db_session.execute(
                select(m.Assignment).where(m.Assignment.resource_type == "personal")
            )
        )
        .scalars()
        .first()
    )
    old_resource = assignment.resource_id
    record = assignment.model_dump()
    record["resource_id"] = resource.id
    content = DOMAIN_BY_NAME["assignments"].export_csv({"assignments": [record]})
    refresh = AsyncMock(return_value=0)
    monkeypatch.setattr("app.services.import_export.common.refresh_resources", refresh)
    result = await transfer.import_area_rows(
        db_session, "assignments", csv_format._read_csv(content), source["admin"]
    )
    assert not result.errors and result.updated == 1
    assert refresh.await_args.args[1] == {old_resource, resource.id}
    assert source["machine"] not in refresh.await_args.args[1]


@pytest.mark.parametrize("default", [False, True])
async def test_calendar_refresh_scopes_explicit_bindings_and_shared_defaults(
    db_session, source, monkeypatch, default
):
    profile = m.WorkWeekProfile(name="Selected calendar", is_default=False)
    db_session.add(profile)
    await db_session.flush()
    binding = m.ResourceWorkProfile(
        resource_id=source["person"],
        profile_id=profile.id,
        valid_from=datetime(2099, 1, 1).date(),
    )
    db_session.add(binding)
    await db_session.commit()
    if default:
        profile = (
            await db_session.execute(
                select(m.WorkWeekProfile).where(m.WorkWeekProfile.is_default.is_(True))
            )
        ).scalar_one()
    record = profile.model_dump()
    record["monday_minutes"] = 123
    content = DOMAIN_BY_NAME["working-time"].export_csv(
        {"sites": [], "work_week_profiles": [record], "holidays": []}
    )
    refresh = AsyncMock(return_value=0)
    monkeypatch.setattr("app.services.import_export.common.refresh_resources", refresh)
    result = await transfer.import_area_rows(
        db_session, "working-time", csv_format._read_csv(content), source["admin"]
    )
    assert not result.errors and result.updated == 1
    assert refresh.await_args.args[1] == (None if default else {source["person"]})


async def test_semantic_error_names_the_file_row_and_field(db_session, source):
    assignment = (
        (
            await db_session.execute(
                select(m.Assignment).where(m.Assignment.resource_type == "personal")
            )
        )
        .scalars()
        .first()
    )
    record = assignment.model_dump()
    record["resource_id"] = uuid4()
    content = DOMAIN_BY_NAME["assignments"].export_csv({"assignments": [record]})
    result = await transfer.import_area_rows(
        db_session, "assignments", csv_format._read_csv(content)
    )
    assert (
        "assignments.csv, row 3, field resource_id: unknown resource"
        in result.errors[0]
    )


@pytest.mark.parametrize("field,value", [("level", "6"), ("valid_from", "not-a-date")])
async def test_typed_field_errors_keep_the_exact_location(
    db_session, source, field, value
):
    rows = csv_format._read_csv(await transfer.export_area(db_session, "personnel"))
    number, row = next(
        (index, row)
        for index, row in enumerate(rows[2:], start=3)
        if row[0] == "personal_resource_skills"
    )
    row[rows[1].index(field)] = value
    result = await transfer.import_area_rows(
        db_session, "personnel", rows, source["admin"]
    )
    assert f"personnel.csv, row {number}, field {field}" in result.errors[0]
    assert value not in result.errors[0]  # Do not echo uploaded field values.


async def test_constraint_error_names_input_fields_without_echoing_values(db_session):
    skill = m.Skill(name="PRIVATE_INPUT_VALUE", resource_type="personal")
    db_session.add(skill)
    await db_session.commit()
    duplicate = skill.model_dump()
    duplicate["id"] = uuid4()
    content = DOMAIN_BY_NAME["skills"].export_csv(
        {"skills": [duplicate], "skill_attributes": []}
    )
    result = await transfer.import_area_rows(
        db_session, "skills", csv_format._read_csv(content)
    )
    assert result.created == result.updated == 0
    assert "skills.csv, row 3, field name:" in result.errors[0]
    assert "nothing was imported" in result.errors[0]
    assert "PRIVATE_INPUT_VALUE" not in result.errors[0]
    assert (
        await db_session.execute(select(func.count()).select_from(m.Skill))
    ).scalar_one() == 1


async def test_default_site_holiday_refreshes_resources_without_explicit_site(
    db_session, source, monkeypatch
):
    person = await db_session.get(m.PersonalResource, source["person"])
    person.site_id = None
    site = (
        await db_session.execute(select(m.Site).where(m.Site.is_default.is_(True)))
    ).scalar_one()
    other_site = m.Site(name="Unrelated site")
    db_session.add(other_site)
    await db_session.flush()
    unrelated = m.PersonalResource(
        name="Unrelated resource", group_id=person.group_id, site_id=other_site.id
    )
    db_session.add(unrelated)
    await db_session.commit()
    holiday = m.Holiday(
        site_id=site.id,
        day=datetime(2099, 4, 1).date(),
        name="Default-site exception",
        working_minutes=0,
    )
    content = DOMAIN_BY_NAME["working-time"].export_csv(
        {"sites": [], "work_week_profiles": [], "holidays": [holiday.model_dump()]}
    )
    refresh = AsyncMock(return_value=0)
    monkeypatch.setattr("app.services.import_export.common.refresh_resources", refresh)
    result = await transfer.import_area_rows(
        db_session, "working-time", csv_format._read_csv(content), source["admin"]
    )
    assert not result.errors and result.created == 1
    affected = refresh.await_args.args[1]
    assert person.id in affected
    assert unrelated.id not in affected
