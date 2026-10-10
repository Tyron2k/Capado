"""Complete CSV migrations preserve persisted data and planning calculations."""

import copy
import io
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from sqlalchemy import func, select

from app import models as m
from app.models.base import ORMModel
from app.models.project import ProjectFolder, WorkPackageDependency
from app.services.baseline_service import snapshot_payload
from app.services.capacity_service import CapacityService
from app.services.import_export import (
    AREA_BY_NAME,
    AREAS,
    DOMAIN_BY_NAME,
    ENTITIES,
    EXCLUDED_TABLES,
    csv_format,
    history,
)
from app.services.import_export import csv_transfer as migration
from app.services.import_export.csv_storage import load_data
from app.services.qualification import HeldQualification, satisfies
from app.services.unmet_requirements_service import (
    compute_coverage,
    get_unmet_requirements,
)
from tests.test_assignment_csv_roundtrip import empty_target


async def _load_data(session):
    return await load_data(session, ENTITIES)


DAY = date(2099, 1, 5)


@pytest.fixture
async def source(db_session):
    """Every supported entity, including data the five original CSVs omitted."""
    site = m.Site(name="Main", region_code="DE-BY", is_default=True)
    retired_site = m.Site(name="Closed", is_active=False)
    profile = m.WorkWeekProfile(name="Standard", is_default=True)
    part_time = m.WorkWeekProfile(
        name="Part time",
        monday_minutes=300,
        tuesday_minutes=360,
        wednesday_minutes=240,
        thursday_minutes=300,
        friday_minutes=180,
    )
    parent = m.ResourceGroup(name="Team", resource_type="personal")
    machines = m.ResourceGroup(name="Team", resource_type="infrastructure")
    empty = m.ResourceGroup(name="Empty", resource_type="personal")
    skill = m.Skill(name="Paint", resource_type="personal")
    machine_skill = m.Skill(name="Machine", resource_type="infrastructure")
    unused = m.Skill(name="Unused", resource_type="personal")
    no_attributes = m.Skill(name="No attributes", resource_type="personal")
    customer = m.Customer(name="Customer", reference="C-1", note="A;B\nC")
    db_session.add_all(
        [
            site,
            retired_site,
            profile,
            part_time,
            parent,
            machines,
            empty,
            skill,
            machine_skill,
            unused,
            no_attributes,
            customer,
        ]
    )
    await db_session.flush()
    child = m.ResourceGroup(name="Team", resource_type="personal", parent_id=parent.id)
    folder = ProjectFolder(
        name="Order", customer_id=customer.id, external_ref="O-42", position=3
    )
    attr = m.SkillAttribute(name="A", skill_id=skill.id)
    machine_attr = m.SkillAttribute(name="Bay", skill_id=machine_skill.id)
    unused_attr = m.SkillAttribute(name="Unused variant", skill_id=unused.id)
    db_session.add_all([child, folder, attr, machine_attr, unused_attr])
    await db_session.flush()
    nested_folder = ProjectFolder(
        name="Order", parent_id=folder.id, external_ref="Nested", position=4
    )
    person = m.PersonalResource(name="Shared", group_id=child.id, site_id=site.id)
    inactive = m.PersonalResource(
        name="Shared", group_id=parent.id, site_id=retired_site.id, is_active=False
    )
    machine = m.InfrastructureResource(
        name="Shared", group_id=machines.id, site_id=site.id
    )
    db_session.add_all([nested_folder, person, inactive, machine])
    await db_session.flush()
    project = m.Project(
        name="Build",
        folder_id=nested_folder.id,
        start_date=DAY,
        end_date=DAY + timedelta(days=10),
        customer_id=customer.id,
        priority="critical",
        position=7,
        external_ref="P-42",
        committed_delivery_date=DAY + timedelta(days=8),
    )
    second_project = m.Project(
        name="Build",
        folder_id=folder.id,
        start_date=DAY,
        end_date=DAY + timedelta(days=10),
    )
    template = m.WorkPackageTemplate(
        name="Paint", description="Standard", lead_time_working_days=3
    )
    db_session.add_all([project, second_project, template])
    await db_session.flush()
    wp = m.WorkPackage(
        name="Paint",
        project_id=project.id,
        start_date=DAY,
        end_date=DAY + timedelta(days=3),
        lead_time_working_days=3,
        completed_at=datetime(2099, 1, 8, 12, 0, 23, 123456, UTC),
    )
    wp2 = m.WorkPackage(
        name="Paint",
        project_id=project.id,
        start_date=DAY + timedelta(days=4),
        end_date=DAY + timedelta(days=7),
    )
    admin = m.User(
        email="admin@example.test",
        name="Source admin",
        role="admin",
        password_hash="SOURCE_SECRET_HASH",
        must_change_password=False,
        external_id="SOURCE_OIDC_BINDING",
    )
    editor = m.User(
        email="editor@example.test",
        name="Planner",
        role="editor",
        password_hash="OTHER_SECRET_HASH",
        must_change_password=False,
        scope_group_ids=[child.id],
        scope_project_ids=[project.id],
        resource_id=person.id,
    )
    db_session.add_all([wp, wp2, admin, editor])
    await db_session.flush()
    held = m.PersonalResourceSkill(
        resource_id=person.id,
        skill_attribute_id=attr.id,
        level=4,
        valid_from=DAY - timedelta(days=10),
        valid_until=DAY + timedelta(days=4),
    )
    infra_held = m.InfrastructureResourceSkill(
        resource_id=machine.id,
        skill_attribute_id=machine_attr.id,
        level=3,
        valid_until=DAY + timedelta(days=30),
    )
    assignments = [
        m.Assignment(
            resource_type="personal",
            resource_id=person.id,
            work_package_id=wp.id,
            start_date=DAY,
            end_date=DAY,
            allocation_percent=33.5,
        ),
        m.Assignment(
            resource_type="personal",
            resource_id=person.id,
            work_package_id=wp.id,
            start_date=DAY,
            end_date=DAY,
            allocation_percent=34.5,
        ),  # same period, distinct allocation and IDs; both must survive transfer
        m.Assignment(
            resource_type="personal",
            resource_id=person.id,
            work_package_id=wp.id,
            start_date=DAY + timedelta(days=2),
            end_date=DAY + timedelta(days=3),
            allocation_percent=66.75,
        ),
        m.Assignment(
            resource_type="personal",
            resource_id=inactive.id,
            work_package_id=wp.id,
            start_date=DAY,
            end_date=DAY,
            allocation_percent=42.125,
        ),
        m.Assignment(
            resource_type="infrastructure",
            resource_id=machine.id,
            work_package_id=wp.id,
            start_at=datetime(2099, 1, 5, 10, 15, 23, 123456, UTC),
            end_at=datetime(2099, 1, 5, 11, 45, 23, 654321, UTC),
        ),
    ]
    baseline = m.Baseline(
        name="Agreed", note="Original plan", created_by=admin.id, is_current=True
    )
    settings = m.OrganizationSettings(
        company_name=r"\N",
        company_subtitle="",
        time_zone="Asia/Tokyo",
        logo_data=b"\x89PNG\r\n\x1a\nexample",
        logo_mime_type="image/png",
        smtp_enabled=True,
        smtp_host="mail.example.test",
        smtp_password="SMTP_SECRET",
        smtp_username="user",
        scheduler_enabled=True,
        planning_freeze_before=DAY - timedelta(days=30),
        digest_recipients="test@example.test",
        maintenance_hour=7,
    )
    db_session.add_all(
        [
            held,
            infra_held,
            *assignments,
            baseline,
            settings,
            m.Holiday(
                site_id=site.id,
                day=DAY + timedelta(days=1),
                name="Closed",
                working_minutes=0,
            ),
            m.Holiday(
                site_id=site.id,
                day=DAY + timedelta(days=2),
                name="Half day",
                working_minutes=240,
            ),
            m.ResourceWorkProfile(
                group_id=parent.id,
                profile_id=part_time.id,
                valid_from=DAY - timedelta(days=20),
            ),
            m.ResourceWorkProfile(
                resource_id=person.id,
                profile_id=profile.id,
                valid_from=DAY + timedelta(days=2),
            ),
            m.ResourceWorkProfile(
                group_id=machines.id,
                profile_id=part_time.id,
                valid_from=DAY - timedelta(days=1),
            ),
            m.ResourceWorkProfile(
                resource_id=machine.id, profile_id=profile.id, valid_from=DAY
            ),
            m.InfrastructureAvailabilityWindow(
                resource_id=machine.id,
                weekday=DAY.weekday(),
                start_time=time(6),
                end_time=time(22),
            ),
            m.Absence(
                resource_id=person.id,
                resource_type="personal",
                reason="planned",
                status="provisional",
                start_date=DAY,
                end_date=DAY,
                allocation_percent=25.5,
                note="Quoted; note\nwith newline",
            ),
            m.Absence(
                resource_id=machine.id,
                resource_type="infrastructure",
                reason="unplanned",
                start_date=DAY + timedelta(days=2),
                end_date=DAY + timedelta(days=2),
            ),
            m.WorkPackageRequirement(
                work_package_id=wp.id,
                skill_id=skill.id,
                skill_attribute_id=attr.id,
                quantity=2,
                requirement_mode="effort_fte",
                min_allocation_percent=33.5,
                min_level=4,
            ),
            m.WorkPackageRequirement(
                work_package_id=wp2.id,
                skill_id=skill.id,
                quantity=1,
                requirement_mode="headcount",
                min_allocation_percent=66.75,
                min_level=5,
            ),
            m.WorkPackageTemplateRequirement(
                template_id=template.id,
                skill_id=skill.id,
                skill_attribute_id=attr.id,
                quantity=1,
                requirement_mode="headcount",
                min_allocation_percent=50.5,
                min_level=3,
            ),
            WorkPackageDependency(
                predecessor_id=wp.id, successor_id=wp2.id, lag_working_days=2
            ),
            m.AuditLog(
                entity_type="users",
                entity_id=admin.id,
                actor_id=admin.id,
                action="updated",
                changes={
                    "password_hash": {"from": "HISTORIC_SECRET", "to": "NEW_SECRET"}
                },
            ),
            m.AuditLog(
                entity_type="assignments",
                entity_id=assignments[0].id,
                actor_id=None,
                action="created",
                changes={"start_date": {"from": None, "to": DAY.isoformat()}},
            ),
        ]
    )
    await db_session.flush()
    db_session.add(
        m.BaselineEntry(
            baseline_id=baseline.id,
            entity_type="work_packages",
            entity_id=wp.id,
            payload=snapshot_payload(wp),
        )
    )
    await db_session.commit()
    return {
        "person": person.id,
        "inactive": inactive.id,
        "machine": machine.id,
        "admin": admin.id,
        "wp": wp.id,
        "held": held.id,
        "settings": settings.id,
    }


@pytest.fixture
async def destination(empty_target):
    admin = m.User(
        email="admin@example.test",
        name="Destination admin",
        role="admin",
        password_hash="DESTINATION_SECRET_HASH",
        external_id="DESTINATION_BINDING",
        must_change_password=False,
    )
    empty_target.add(admin)
    empty_target.add(
        m.OrganizationSettings(
            company_name="Before import", smtp_password="TARGET_SMTP_SECRET"
        )
    )
    await empty_target.commit()
    return admin.id


async def planning_signature(session, refs):
    utilization = await CapacityService(session).calculate_utilization(
        refs["person"], DAY, DAY + timedelta(days=3)
    )
    held = (
        (
            await session.execute(
                select(m.PersonalResourceSkill).where(
                    m.PersonalResourceSkill.id == refs["held"]
                )
            )
        )
        .scalars()
        .one()
    )
    qualification = HeldQualification(
        valid_from=held.valid_from, valid_until=held.valid_until, level=held.level
    )
    requirements = (
        (await session.execute(select(m.WorkPackageRequirement))).scalars().all()
    )
    assignments = (
        (
            await session.execute(
                select(m.Assignment).where(m.Assignment.resource_type == "personal")
            )
        )
        .scalars()
        .all()
    )
    coverage = {
        req.id: compute_coverage(
            req.requirement_mode,
            req.min_allocation_percent,
            [
                (a.resource_id, a.allocation_percent)
                for a in assignments
                if a.work_package_id == req.work_package_id
            ],
        )
        for req in requirements
    }
    unmet = await get_unmet_requirements(session, resource_type="personal")
    return (
        utilization,
        [
            satisfies(qualification, 4, DAY, DAY + timedelta(days=3)),
            satisfies(qualification, 5, DAY, DAY + timedelta(days=3)),
            satisfies(qualification, 4, DAY, DAY + timedelta(days=5)),
        ],
        coverage,
        sorted((u.work_package_id, u.assigned_quantity, u.gap) for u in unmet),
    )


async def test_complete_migration_preserves_all_public_fields_and_calculations(
    db_session, empty_target, source, destination
):
    signature = await planning_signature(db_session, source)
    assert signature[0][0].available_minutes > 0
    assert signature[1] == [True, False, False]
    archive = await migration.export_migration(db_session)
    expected = migration.parse_migration(archive)
    assert all(expected[entity.name] for entity in ENTITIES)
    result = await migration.import_migration(empty_target, archive, destination)
    assert result.errors == []
    assert result.updated == 1
    assert result.created == sum(len(rows) for rows in expected.values()) - 1
    assert await planning_signature(empty_target, source) == signature

    actual = migration.parse_migration(await migration.export_migration(empty_target))
    # The bootstrap admin keeps its identity/login; historical actor references follow it.
    for row in expected["users"]:
        if row["id"] == source["admin"]:
            row["id"] = destination
    for row in expected["baselines"]:
        if row["created_by"] == source["admin"]:
            row["created_by"] = destination
    for row in expected["audit_log"]:
        if row["actor_id"] == source["admin"]:
            row["actor_id"] = destination
        if row["entity_type"] == "users" and row["entity_id"] == source["admin"]:
            row["entity_id"] = destination
    for row in expected["organization_settings"]:
        row.update(smtp_enabled=False, scheduler_enabled=False)
    markers = [
        row for row in actual["audit_log"] if row["entity_type"] == "csv_migration"
    ]
    assert len(markers) == 1 and markers[0]["actor_id"] == destination
    actual["audit_log"] = [
        row for row in actual["audit_log"] if row["entity_type"] != "csv_migration"
    ]
    for entity in ENTITIES:
        assert sorted(actual[entity.name], key=lambda row: row["id"]) == sorted(
            expected[entity.name], key=lambda row: row["id"]
        ), entity.name
    users = (await empty_target.execute(select(m.User))).scalars().all()
    assert (
        next(u for u in users if u.id == destination).password_hash
        == "DESTINATION_SECRET_HASH"
    )
    imported = next(u for u in users if u.id != destination)
    assert (
        imported.password_hash == ""
        and imported.must_change_password
        and imported.external_id is None
    )
    assert (
        await empty_target.execute(select(m.OrganizationSettings))
    ).scalars().one().smtp_password == ""


async def test_export_never_contains_credentials_even_in_old_history(
    db_session, source
):
    archive = await migration.export_migration(db_session)
    with ZipFile(io.BytesIO(archive)) as zipped:
        content = b"\n".join(zipped.read(name) for name in zipped.namelist())
        assert all(name.endswith(".csv") for name in zipped.namelist())
    for secret in (
        b"SOURCE_SECRET_HASH",
        b"OTHER_SECRET_HASH",
        b"SOURCE_OIDC_BINDING",
        b"SMTP_SECRET",
        b"HISTORIC_SECRET",
        b"NEW_SECRET",
    ):
        assert secret not in content
    assert b"<redacted>" in content


def test_every_table_and_column_has_an_explicit_migration_decision():
    assert {entity.name for entity in ENTITIES} | EXCLUDED_TABLES == set(
        ORMModel.metadata.tables
    )
    omitted = {
        "users": {"password_hash", "external_id", "must_change_password"},
        "organization_settings": {"smtp_password"},
    }
    for entity in ENTITIES:
        assert set(entity.columns) | omitted.get(entity.name, set()) == set(
            entity.table.columns.keys()
        )
        assert not (set(entity.columns) & history._SECRET_KEYS)


async def test_existing_target_is_never_overwritten(
    db_session, empty_target, source, destination
):
    sentinel = m.Site(name="Existing data")
    empty_target.add(sentinel)
    await empty_target.commit()
    sentinel_id = sentinel.id
    result = await migration.import_migration(
        empty_target, await migration.export_migration(db_session), destination
    )
    assert result.created == result.updated == 0
    assert "empty destination" in result.errors[0]
    assert (await empty_target.execute(select(m.Site.id))).scalars().all() == [
        sentinel_id
    ]
    assert (
        await empty_target.execute(select(m.OrganizationSettings))
    ).scalars().one().company_name == "Before import"


async def test_database_constraint_failure_rolls_back_every_entity(
    db_session, empty_target, source, destination
):
    data = migration.parse_migration(await migration.export_migration(db_session))
    duplicate = copy.deepcopy(data["skills"][0])
    duplicate["id"] = uuid4()
    data["skills"].append(duplicate)
    archive = migration._build_archive(data)
    result = await migration.import_migration(empty_target, archive, destination)
    assert result.created == result.updated == 0
    assert "nothing was imported" in result.errors[0]
    assert (
        await empty_target.execute(select(func.count()).select_from(m.Site))
    ).scalar_one() == 0
    assert (
        await empty_target.execute(select(m.OrganizationSettings))
    ).scalars().one().company_name == "Before import"


@pytest.mark.parametrize("unexpected", [False, True])
async def test_late_domain_failure_rolls_back_the_entire_bundle(
    db_session, empty_target, source, destination, monkeypatch, unexpected
):
    archive = await migration.export_migration(db_session)
    write_history = history.write_import

    async def fail_after_history(session, batch, context):
        result = await write_history(session, batch, context)
        # The last domain has already written its records: earlier domains
        # must still be uncommitted and belong to the same transaction.
        assert result.created > 0
        assert (
            await session.execute(select(func.count()).select_from(m.Assignment))
        ).scalar_one() > 0
        if unexpected:
            raise RuntimeError("Late domain failure")
        from sqlalchemy import insert

        user = context.existing["users"][0]
        await session.execute(
            insert(ORMModel.metadata.tables["users"]).values(
                id=uuid4(),
                email=user["email"],
                name="Duplicate",
                role="viewer",
                password_hash="",
            )
        )
        return result

    monkeypatch.setattr(history, "write_import", fail_after_history)
    if unexpected:
        with pytest.raises(RuntimeError, match="Late domain failure"):
            await migration.import_migration(empty_target, archive, destination)
    else:
        result = await migration.import_migration(empty_target, archive, destination)
        assert result.created == result.updated == 0
        assert "nothing was imported" in result.errors[0]
    for model in (m.Site, m.Project, m.Assignment, m.Baseline, m.AuditLog):
        assert (
            await empty_target.execute(select(func.count()).select_from(model))
        ).scalar_one() == 0
    settings = (
        (await empty_target.execute(select(m.OrganizationSettings))).scalars().one()
    )
    assert settings.company_name == "Before import"
    users = (await empty_target.execute(select(m.User))).scalars().all()
    assert len(users) == 1
    assert users[0].id == destination
    assert users[0].password_hash == "DESTINATION_SECRET_HASH"


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda d: d["assignments"][0].update(resource_id=uuid4()), "unknown resource"),
        (lambda d: d["personal_resource_skills"][0].update(level=6), "invalid field"),
        (
            lambda d: d["work_package_requirements"][0].update(
                requirement_mode="guess"
            ),
            "invalid field",
        ),
        (
            lambda d: d["resource_work_profiles"][0].update(
                group_id=None, resource_id=None
            ),
            "exactly one",
        ),
        (
            lambda d: d["resource_groups"][0].update(
                parent_id=d["resource_groups"][0]["id"]
            ),
            "Cyclic",
        ),
        (lambda d: d["users"][0].update(scope_group_ids=[uuid4()]), "Unknown user"),
        (
            lambda d: d["organization_settings"][0].update(time_zone="Unknown/Zone"),
            "time zone",
        ),
    ],
)
async def test_invalid_packages_are_atomic(
    db_session, empty_target, source, destination, mutation, message
):
    data = migration.parse_migration(await migration.export_migration(db_session))
    mutation(data)
    result = await migration.import_migration(
        empty_target, migration._build_archive(data), destination
    )
    assert result.created == result.updated == 0
    assert message.lower() in result.errors[0].lower()
    assert (
        await empty_target.execute(select(func.count()).select_from(m.Site))
    ).scalar_one() == 0


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "duplicate", "corrupt", "version"]
)
async def test_incomplete_or_modified_archive_is_rejected(db_session, source, kind):
    archive = await migration.export_migration(db_session)
    with ZipFile(io.BytesIO(archive)) as zipped:
        files = {name: zipped.read(name) for name in zipped.namelist()}
    if kind == "missing":
        del files["skills.csv"]
    elif kind == "extra":
        files["../outside.csv"] = b"invalid"
    elif kind == "corrupt":
        files["skills.csv"] += b"extra;row\n"
    elif kind == "version":
        files["manifest.csv"] = files["manifest.csv"].replace(
            b"migration;2;", b"migration;999;"
        )
    out = io.BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as zipped:
        for name, content in files.items():
            zipped.writestr(name, content)
        if kind == "duplicate":
            zipped.writestr("skills.csv", files["skills.csv"])
    with pytest.raises(ValueError):
        migration.parse_migration(out.getvalue())


async def test_expanded_size_and_row_limits_are_enforced(
    db_session, source, monkeypatch
):
    archive = await migration.export_migration(db_session)
    monkeypatch.setattr(migration, "MAX_EXPANDED_BYTES", 10)
    with pytest.raises(ValueError, match="expanded limit"):
        migration.parse_migration(archive)
    monkeypatch.setattr(migration, "MAX_EXPANDED_BYTES", 100 * 1024 * 1024)
    monkeypatch.setattr(migration, "MAX_ROWS", 1)
    with pytest.raises(ValueError, match="row limit"):
        migration.parse_migration(archive)


async def test_empty_source_still_restores_disabled_maintenance_and_keeps_bootstrap(
    empty_target, destination
):
    data = {entity.name: [] for entity in ENTITIES}
    result = await migration.import_migration(
        empty_target, migration._build_archive(data), destination
    )
    assert result.errors == []
    settings = (
        (await empty_target.execute(select(m.OrganizationSettings))).scalars().one()
    )
    assert not settings.scheduler_enabled and not settings.smtp_enabled
    admin = (await empty_target.execute(select(m.User))).scalars().one()
    assert admin.id == destination and admin.password_hash == "DESTINATION_SECRET_HASH"


async def test_standalone_exports_are_exactly_the_zip_members(db_session, source):
    """One format and serializer: no richer hidden migration-only export."""
    with ZipFile(io.BytesIO(await migration.export_migration(db_session))) as zipped:
        assert set(zipped.namelist()) == {area.name + ".csv" for area in AREAS} | {
            "manifest.csv"
        }
        for area in AREAS:
            assert await migration.export_area(db_session, area.name) == zipped.read(
                area.name + ".csv"
            )
    data = await _load_data(db_session)
    groups = {row["id"]: row["resource_type"] for row in data["resource_groups"]}
    personal = {row["id"] for row in data["personal_resources"]}
    for name, kind in (("personnel", "personal"), ("infrastructure", "infrastructure")):
        parsed = DOMAIN_BY_NAME[name].parse_csv(
            csv_format._read_csv(await migration.export_area(db_session, name)),
        )
        bindings = parsed.data["resource_work_profiles"]
        assert len(bindings) == 2
        assert all(
            (
                groups[row["group_id"]]
                if row["group_id"]
                else "personal"
                if row["resource_id"] in personal
                else "infrastructure"
            )
            == kind
            for row in bindings
        )
    assert {name for area in AREAS for name in area.tables} == {
        e.name for e in ENTITIES
    }


async def test_all_standalone_csvs_restore_the_same_data_and_calculations(
    db_session, empty_target, source, destination
):
    """Manual area imports retain everything, including bootstrap-linked history."""
    signature = await planning_signature(db_session, source)
    expected = migration.parse_migration(await migration.export_migration(db_session))
    for area in AREAS:
        rows = csv_format._read_csv(await migration.export_area(db_session, area.name))
        result = await migration.import_area_rows(
            empty_target, area.name, rows, destination
        )
        assert result.errors == [], (area.name, result.errors)
    assert await planning_signature(empty_target, source) == signature
    actual = await _load_data(empty_target)
    # Compare every field, ignoring only the documented destination login and
    # activation changes, and the additional audit events for the ten imports.
    for row in expected["users"]:
        if row["id"] == source["admin"]:
            row["id"] = destination
    for row in expected["baselines"]:
        if row["created_by"] == source["admin"]:
            row["created_by"] = destination
    for row in expected["audit_log"]:
        if row["actor_id"] == source["admin"]:
            row["actor_id"] = destination
        if row["entity_type"] == "users" and row["entity_id"] == source["admin"]:
            row["entity_id"] = destination
    for row in expected["organization_settings"]:
        row.update(smtp_enabled=False, scheduler_enabled=False)
    actual["audit_log"] = [
        row for row in actual["audit_log"] if row["entity_type"] != "csv_import"
    ]
    # Compare through the codec to normalize SQLite timestamps and redact history.
    actual = migration.parse_migration(migration._build_archive(actual))
    for entity in ENTITIES:
        assert sorted(actual[entity.name], key=lambda row: row["id"]) == sorted(
            expected[entity.name], key=lambda row: row["id"]
        ), entity.name
    admin = (
        await empty_target.execute(select(m.User).where(m.User.id == destination))
    ).scalar_one()
    assert admin.password_hash == "DESTINATION_SECRET_HASH"


async def test_partial_area_update_uses_ids_preserves_omitted_data_and_existing_credentials(
    db_session, empty_target, source, destination
):
    result = await migration.import_migration(
        empty_target, await migration.export_migration(db_session), destination
    )
    assert not result.errors
    data = await _load_data(empty_target)
    selected = data["personal_resources"][0]
    selected["name"] = "Renamed by CSV"
    selected["is_active"] = False
    data["personal_resources"] = [selected]
    for name in (
        "resource_groups",
        "personal_resource_skills",
        "resource_work_profiles",
    ):
        data[name] = []
    area = AREA_BY_NAME["personnel"]
    result = await migration.import_area_rows(
        empty_target,
        area.name,
        csv_format._read_csv(DOMAIN_BY_NAME[area.name].export_csv(data)),
        destination,
    )
    assert not result.errors and result.updated == 1 and result.created == 0
    await empty_target.refresh(
        (
            await empty_target.execute(
                select(m.PersonalResource).where(
                    m.PersonalResource.id == selected["id"]
                )
            )
        ).scalar_one()
    )
    restored = (await empty_target.execute(select(m.PersonalResource))).scalars().all()
    assert len(restored) == 2
    assert (
        next(row for row in restored if row.id == selected["id"]).name
        == "Renamed by CSV"
    )
    assert (
        await empty_target.execute(
            select(func.count()).select_from(m.PersonalResourceSkill)
        )
    ).scalar_one() == 1
    # Reimport account data updates public fields without invalidating credentials.
    data = await _load_data(empty_target)
    area = AREA_BY_NAME["administration"]
    result = await migration.import_area_rows(
        empty_target,
        area.name,
        csv_format._read_csv(DOMAIN_BY_NAME[area.name].export_csv(data)),
        destination,
    )
    assert not result.errors
    admin = (
        await empty_target.execute(select(m.User).where(m.User.id == destination))
    ).scalar_one()
    assert admin.password_hash == "DESTINATION_SECRET_HASH"


async def test_missing_area_dependencies_reject_the_entire_file(
    db_session, empty_target, source, destination
):
    rows = csv_format._read_csv(await migration.export_area(db_session, "personnel"))
    result = await migration.import_area_rows(
        empty_target, "personnel", rows, destination
    )
    assert result.created == result.updated == 0 and result.errors
    assert (
        await empty_target.execute(select(func.count()).select_from(m.ResourceGroup))
    ).scalar_one() == 0
    assert (
        await empty_target.execute(select(func.count()).select_from(m.PersonalResource))
    ).scalar_one() == 0


async def test_area_database_constraint_failure_rolls_back_updates_and_additions(
    db_session, source
):
    data = await _load_data(db_session)
    data["skills"][0]["name"] = "Changed name must roll back"
    duplicate = copy.deepcopy(data["skills"][1])
    duplicate["id"] = uuid4()
    data["skills"].append(duplicate)
    area = AREA_BY_NAME["skills"]
    result = await migration.import_area_rows(
        db_session,
        area.name,
        csv_format._read_csv(DOMAIN_BY_NAME[area.name].export_csv(data)),
    )
    assert (
        result.created == result.updated == 0
        and "nothing was imported" in result.errors[0]
    )
    actual = await _load_data(db_session)
    assert "Changed name must roll back" not in {
        row["name"] for row in actual["skills"]
    }
    assert len(actual["skills"]) == 4


@pytest.mark.parametrize(
    "kind", ["wrong-area", "version", "duplicate-id", "unused-column", "foreign-type"]
)
async def test_area_format_errors_are_atomic(db_session, source, kind):
    rows = csv_format._read_csv(await migration.export_area(db_session, "personnel"))
    if kind == "wrong-area":
        rows[0][2] = "infrastructure"
    elif kind == "version":
        rows[0][1] = "999"
    elif kind == "duplicate-id":
        rows.append(rows[2])
    elif kind == "unused-column":
        rows[2][rows[1].index("valid_until")] = "2099-01-01"
    else:
        rows[2][rows[1].index("resource_type")] = "infrastructure"
    result = await migration.import_area_rows(db_session, "personnel", rows)
    assert result.created == result.updated == 0 and result.errors


async def test_area_can_move_an_existing_child_under_a_new_parent(db_session, source):
    data = await _load_data(db_session)
    child = next(row for row in data["resource_groups"] if row["parent_id"] is not None)
    parent = copy.deepcopy(
        next(row for row in data["resource_groups"] if row["id"] == child["parent_id"])
    )
    parent.update(id=uuid4(), name="New parent")
    child["parent_id"] = parent["id"]
    data["resource_groups"] = [child, parent]
    for name in (
        "personal_resources",
        "personal_resource_skills",
        "resource_work_profiles",
    ):
        data[name] = []
    area = AREA_BY_NAME["personnel"]
    result = await migration.import_area_rows(
        db_session,
        area.name,
        csv_format._read_csv(DOMAIN_BY_NAME[area.name].export_csv(data)),
    )
    assert not result.errors
    assert result.created == result.updated == 1
    current = await _load_data(db_session)
    assert (
        next(row for row in current["resource_groups"] if row["id"] == child["id"])[
            "parent_id"
        ]
        == parent["id"]
    )


async def test_personnel_import_rejects_a_binding_for_infrastructure(
    db_session, source
):
    rows = csv_format._read_csv(await migration.export_area(db_session, "personnel"))
    data = await _load_data(db_session)
    infra_group = next(
        row["id"]
        for row in data["resource_groups"]
        if row["resource_type"] == "infrastructure"
    )
    binding = next(row for row in rows[2:] if row[0] == "resource_work_profiles")
    binding[rows[1].index("resource_id")] = csv_format._NULL
    binding[rows[1].index("group_id")] = str(infra_group)
    result = await migration.import_area_rows(db_session, "personnel", rows)
    assert result.created == result.updated == 0
    assert "another CSV area" in result.errors[0]
