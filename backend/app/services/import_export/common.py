"""Shared building blocks for the import/export domain modules.

Contains the :class:`ImportResult` summary object, the skill-matrix data
loader and workbook builder, the flat resource workbook/CSV builders, the
generic resource import routine, and the header-parsing helper. These pieces
are reused by the personnel and infrastructure domain modules (and, in the
case of :class:`ImportResult` and :func:`_parse_header`, by every domain).
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy import Result, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.skill import (
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    Skill,
    SkillAttribute,
)

from .shape import SHAPE_REJECTION_MESSAGES, ImportShape, detect_import_shape


@dataclass
class ImportResult:
    """Summary of an import operation."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ===========================================================================
# Skill Matrix Export (shared by personnel and infrastructure)
# ===========================================================================


@dataclass
class _MatrixData:
    """Pre-loaded data for building a skill matrix workbook."""

    columns: list[tuple[str, str]]  # (skill_name, attribute_name) ordered
    resources: list[tuple[str, str, set[UUID]]]  # (name, group, set of attr_ids)
    attr_id_order: list[UUID]  # same order as columns


async def _load_matrix_data(
    session: AsyncSession,
    *,
    resource_type: str,
) -> _MatrixData:
    """Load all data needed to build a skill matrix for the given resource type.

    Loads skills (filtered by resource_type), their attributes, active
    resources, and resource–skill assignments in bulk queries.

    Args:
        session: Async database session.
        resource_type: 'personal' or 'infrastructure'.

    Returns:
        _MatrixData with column definitions and per-resource skill sets.

    """
    # 1. Load skills for this resource type, ordered by name
    skills = list(
        (
            await session.execute(
                select(Skill)
                .where(Skill.resource_type == resource_type)
                .order_by(Skill.name.asc())
            )
        )
        .scalars()
        .all()
    )
    skill_ids = [s.id for s in skills]
    skill_map: dict[UUID, str] = {s.id: s.name for s in skills}

    # 2. Load attributes for those skills, ordered by skill then name
    attributes: list[SkillAttribute] = []
    if skill_ids:
        attributes = list(
            (
                await session.execute(
                    select(SkillAttribute)
                    .where(SkillAttribute.skill_id.in_(skill_ids))
                    .order_by(SkillAttribute.skill_id, SkillAttribute.name.asc())
                )
            )
            .scalars()
            .all()
        )

    # Build column order: grouped by skill, then alphabetical attribute within
    # Reorder attributes to follow the skill order
    skill_order = {sid: idx for idx, sid in enumerate(skill_ids)}
    attributes.sort(key=lambda a: (skill_order.get(a.skill_id, 999), a.name))

    columns: list[tuple[str, str]] = []
    attr_id_order: list[UUID] = []
    for attr in attributes:
        columns.append((skill_map[attr.skill_id], attr.name))
        attr_id_order.append(attr.id)

    # 3. Load active resources with their groups
    if resource_type == "personal":
        res_stmt = (
            select(
                PersonalResource.id,
                PersonalResource.name,
                ResourceGroup.name.label("group_name"),
            )
            .join(ResourceGroup, PersonalResource.group_id == ResourceGroup.id)
            .where(PersonalResource.is_active.is_(True))
            .order_by(ResourceGroup.name.asc(), PersonalResource.name.asc())
        )
    else:
        res_stmt = (
            select(
                InfrastructureResource.id,
                InfrastructureResource.name,
                ResourceGroup.name.label("group_name"),
            )
            .join(ResourceGroup, InfrastructureResource.group_id == ResourceGroup.id)
            .where(InfrastructureResource.is_active.is_(True))
            .order_by(ResourceGroup.name.asc(), InfrastructureResource.name.asc())
        )

    res_result = await session.execute(res_stmt)
    resource_rows = res_result.all()
    resource_ids = [row.id for row in resource_rows]

    # 4. Load skill assignments for all resources
    resource_attrs: dict[UUID, set[UUID]] = {rid: set() for rid in resource_ids}
    if resource_ids and attr_id_order:
        if resource_type == "personal":
            skill_stmt = select(
                PersonalResourceSkill.resource_id,
                PersonalResourceSkill.skill_attribute_id,
            ).where(PersonalResourceSkill.resource_id.in_(resource_ids))
        else:
            skill_stmt = select(
                InfrastructureResourceSkill.resource_id,
                InfrastructureResourceSkill.skill_attribute_id,
            ).where(InfrastructureResourceSkill.resource_id.in_(resource_ids))

        skill_result = await session.execute(skill_stmt)
        for row in skill_result.all():
            resource_attrs[row.resource_id].add(row.skill_attribute_id)

    # 5. Build resource list with their attribute sets
    resources: list[tuple[str, str, set[UUID]]] = []
    for row in resource_rows:
        resources.append((row.name, row.group_name, resource_attrs.get(row.id, set())))

    return _MatrixData(
        columns=columns,
        resources=resources,
        attr_id_order=attr_id_order,
    )


def _build_skill_matrix_xlsx(data: _MatrixData, sheet_title: str) -> bytes:
    """Build a polished skill matrix Excel workbook with grouped resources.

    Visual design:
    - Row 1: Skill names merged across attributes (dark blue, white text).
    - Row 2: "Name", "Group", attribute names (light blue).
    - Group separator rows (soft green, medium border).
    - Alternating row shading (zebra stripes) within each group.
    - "X" markers in green-highlighted cells.
    - Thin borders on all data cells.
    - Auto-filter enabled on the attribute header row.
    - Freeze panes at C3 (Name + Group stay visible when scrolling).

    Args:
        data: Pre-loaded matrix data (resources pre-sorted by group, then name).
        sheet_title: Title for the worksheet.

    Returns:
        Excel file as bytes.

    """
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title

    num_fixed_cols = 2  # Name, Group
    num_attr_cols = len(data.columns)
    total_cols = num_fixed_cols + num_attr_cols

    # --- Style definitions ---
    font_header_skill = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    font_header_attr = Font(name="Calibri", bold=True, color="1F3864", size=10)
    font_group = Font(name="Calibri", bold=True, color="1F4E28", size=10)
    font_data = Font(name="Calibri", size=10)
    font_x = Font(name="Calibri", bold=True, color="2E7D32", size=10)

    fill_skill_row = PatternFill(
        start_color="2F5496", end_color="2F5496", fill_type="solid"
    )
    fill_attr_row = PatternFill(
        start_color="D6E4F0", end_color="D6E4F0", fill_type="solid"
    )
    fill_group = PatternFill(
        start_color="E2EFDA", end_color="E2EFDA", fill_type="solid"
    )
    fill_stripe = PatternFill(
        start_color="F7F7F7", end_color="F7F7F7", fill_type="solid"
    )
    fill_x = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")

    thin_side = Side(style="thin", color="D0D0D0")
    border_all = Border(
        left=thin_side, right=thin_side, top=thin_side, bottom=thin_side
    )
    border_group = Border(
        left=thin_side,
        right=thin_side,
        top=Side(style="medium", color="8DB4A0"),
        bottom=Side(style="medium", color="8DB4A0"),
    )

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    # --- Row 1: Skill names (merged, dark blue, white text) ---
    ws.row_dimensions[1].height = 24

    if num_attr_cols > 0:
        current_skill: str | None = None
        merge_start: int = 0
        for col_idx, (skill_name, _attr_name) in enumerate(data.columns):
            col = num_fixed_cols + 1 + col_idx
            if skill_name != current_skill:
                if current_skill is not None and col - 1 > merge_start:
                    ws.merge_cells(
                        start_row=1,
                        start_column=merge_start,
                        end_row=1,
                        end_column=col - 1,
                    )
                current_skill = skill_name
                merge_start = col
                ws.cell(row=1, column=col, value=skill_name)

        last_col = num_fixed_cols + num_attr_cols
        if current_skill is not None and last_col > merge_start:
            ws.merge_cells(
                start_row=1,
                start_column=merge_start,
                end_row=1,
                end_column=last_col,
            )

    for col in range(1, total_cols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = fill_skill_row
        cell.font = font_header_skill
        cell.alignment = align_center
        cell.border = border_all

    # --- Row 2: "Name", "Group", attribute names (light blue) ---
    ws.row_dimensions[2].height = 20
    ws.cell(row=2, column=1, value="Name")
    ws.cell(row=2, column=2, value="Group")

    for col_idx, (_skill_name, attr_name) in enumerate(data.columns):
        ws.cell(row=2, column=num_fixed_cols + 1 + col_idx, value=attr_name)

    for col in range(1, total_cols + 1):
        cell = ws.cell(row=2, column=col)
        cell.fill = fill_attr_row
        cell.font = font_header_attr
        cell.alignment = align_center
        cell.border = border_all

    # --- Data rows grouped by resource group ---
    current_row = 3
    current_group: str | None = None
    row_in_group = 0

    for name, group, attr_ids in data.resources:
        # Group header row
        if group != current_group:
            current_group = group
            row_in_group = 0
            ws.row_dimensions[current_row].height = 20
            ws.cell(row=current_row, column=1, value=group)
            if total_cols > 1:
                ws.merge_cells(
                    start_row=current_row,
                    start_column=1,
                    end_row=current_row,
                    end_column=total_cols,
                )
            for col in range(1, total_cols + 1):
                cell = ws.cell(row=current_row, column=col)
                cell.fill = fill_group
                cell.font = font_group
                cell.alignment = align_left
                cell.border = border_group
            current_row += 1

        # Data row with zebra striping
        is_stripe = row_in_group % 2 == 1
        ws.cell(row=current_row, column=1, value=name).font = font_data
        ws.cell(row=current_row, column=1).alignment = align_left
        ws.cell(row=current_row, column=2, value=group).font = font_data
        ws.cell(row=current_row, column=2).alignment = align_left

        for col in range(1, total_cols + 1):
            cell = ws.cell(row=current_row, column=col)
            cell.border = border_all
            if is_stripe:
                cell.fill = fill_stripe

        for col_idx, attr_id in enumerate(data.attr_id_order):
            col = num_fixed_cols + 1 + col_idx
            if attr_id in attr_ids:
                cell = ws.cell(row=current_row, column=col, value="X")
                cell.font = font_x
                cell.alignment = align_center
                cell.fill = fill_x

        current_row += 1
        row_in_group += 1

    # --- Column widths ---
    ws.column_dimensions[get_column_letter(1)].width = 28
    ws.column_dimensions[get_column_letter(2)].width = 22
    for col_idx in range(num_attr_cols):
        col_letter = get_column_letter(num_fixed_cols + 1 + col_idx)
        attr_name = data.columns[col_idx][1]
        ws.column_dimensions[col_letter].width = max(len(attr_name) + 3, 10)

    # Auto-filter on header row 2
    if total_cols > 0:
        ws.auto_filter.ref = f"A2:{get_column_letter(total_cols)}{current_row - 1}"

    # Freeze panes: fix Name + Group columns and the 2 header rows
    ws.freeze_panes = "C3"

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _build_flat_resource_xlsx(rows: list[tuple], sheet_title: str) -> bytes:
    """Build a flat resource Excel workbook (Name, Group, Skill, Attribute, Site).

    Used for both personnel and infrastructure exports when the flat
    (importable) format is requested rather than the matrix.

    Args:
        rows: List of (name, group_name, skill_name, attr_name) tuples.
        sheet_title: Worksheet title ("Personnel" or "Infrastructure").

    Returns:
        Excel file as bytes.

    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(["Name", "Group", "Skill", "Attribute", "Site"])
    for name, group_name, skill_name, attr_name, site_name in rows:
        ws.append(
            [name, group_name, skill_name or "", attr_name or "", site_name or ""]
        )
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _build_flat_resource_csv(rows: list[tuple]) -> str:
    """Build a flat resource CSV (Name;Group;Skill;Attribute;Site).

    Used for both personnel and infrastructure CSV exports.

    Args:
        rows: List of (name, group_name, skill_name, attr_name) tuples.

    Returns:
        CSV content as string.

    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Name", "Group", "Skill", "Attribute", "Site"])
    for name, group_name, skill_name, attr_name, site_name in rows:
        writer.writerow(
            [name, group_name, skill_name or "", attr_name or "", site_name or ""]
        )
    return output.getvalue()


async def _import_resources(
    session: AsyncSession,
    rows: list[tuple],
    *,
    # The two concrete classes rather than bare `type`: bare `type` hides every attribute
    # access below from the type checker, which is exactly the check that catches a renamed
    # column. Named as a union because this function genuinely serves both.
    resource_model: type[PersonalResource] | type[InfrastructureResource],
    skill_model: type,
    resource_type: ResourceType,
) -> ImportResult:
    """Generic resource import for both personal and infrastructure.

    Each row must have at least Name and Group. Optionally, Skill and
    Attribute columns create skill assignments inline. Skills and
    SkillAttributes are auto-created if they don't exist.

    Args:
        session: Database session.
        rows: Parsed rows including header.
        resource_model: SQLModel class (PersonalResource or InfrastructureResource).
        skill_model: Skill assignment class (PersonalResourceSkill or
            InfrastructureResourceSkill).
        resource_type: ResourceType enum value for new groups/skills.

    Returns:
        Import result with counts.

    """
    result = ImportResult()

    if not rows:
        result.errors.append("File is empty.")
        return result

    # Name the file BEFORE trying to read it. The old check ("Header must have at least: Name, Group")
    # was correct but blamed the reader's edits for having picked the wrong export — the skill-matrix
    # workbook fails it for structural reasons no amount of editing can fix.
    shape = detect_import_shape(rows)
    if shape is not ImportShape.FLAT:
        result.errors.append(SHAPE_REJECTION_MESSAGES[shape])
        return result

    # Pre-load caches
    all_groups_result = await session.execute(select(ResourceGroup))
    groups_by_name: dict[str, ResourceGroup] = {
        g.name.lower(): g for g in all_groups_result.scalars().all()
    }

    skill_result = await session.execute(select(Skill))
    skills_by_name: dict[str, Skill] = {
        s.name.lower(): s for s in skill_result.scalars().all()
    }

    attr_result = await session.execute(select(SkillAttribute))
    attrs_by_key: dict[tuple[UUID, str], SkillAttribute] = {
        (a.skill_id, a.name.lower()): a for a in attr_result.scalars().all()
    }

    # The model is chosen at runtime, so the row type is not statically known.
    assign_result: Result[Any] = await session.execute(select(skill_model))
    existing_assignments: set[tuple[UUID, UUID]] = {
        (a.resource_id, a.skill_attribute_id) for a in assign_result.scalars().all()
    }

    # Sites are resolved, never created — see resolve_site. Keyed by real name so the rejection
    # message can quote them back unmangled. Only loaded when the file actually has the column.
    site_column = _site_column_index(_parse_header(rows[0]))
    sites_by_name: dict[str, UUID] = {}
    if site_column is not None:
        sites_result = await session.execute(select(Site))
        sites_by_name = {s.name: s.id for s in sites_result.scalars().all()}

    for row_idx, row in enumerate(rows[1:], start=2):
        cells = [str(cell).strip() if cell else "" for cell in row]
        name = cells[0] if len(cells) > 0 else ""
        group_name = cells[1] if len(cells) > 1 else ""
        skill_name = cells[2] if len(cells) > 2 else ""
        attr_name = cells[3] if len(cells) > 3 else ""

        if not name and not group_name:
            continue
        if not name or not group_name:
            result.errors.append(f"Row {row_idx}: Name and Group are required.")
            continue

        # Resolve the site BEFORE touching the resource, so a rejected row changes nothing. An
        # absent column leaves the site alone; a present-but-empty cell clears it.
        site_id: UUID | None = None
        if site_column is not None:
            raw_site = cells[site_column] if len(cells) > site_column else ""
            site_id, site_error = resolve_site(raw_site, sites_by_name)
            if site_error is not None:
                result.errors.append(f"Row {row_idx}: {site_error}")
                continue

        # Find or create resource
        stmt: Any = (
            select(resource_model)
            .join(ResourceGroup, resource_model.group_id == ResourceGroup.id)
            .where(
                func.lower(resource_model.name) == name.lower(),
                func.lower(ResourceGroup.name) == group_name.lower(),
                resource_model.is_active == True,  # noqa: E712
            )
        )
        db_result = await session.execute(stmt)
        resource = db_result.scalars().first()

        if resource:
            # An existing resource is UPDATED when the file carries a site column, because the
            # Excel round-trip is documented as a way to edit — including to a blank cell, which
            # removes the site. Without the column the field is left exactly as it was.
            if site_column is not None and resource.site_id != site_id:
                resource.site_id = site_id
                session.add(resource)
                result.updated += 1
            elif not skill_name:
                result.skipped += 1
        else:
            group = groups_by_name.get(group_name.lower())
            if not group:
                group = ResourceGroup(name=group_name, resource_type=resource_type)
                session.add(group)
                await session.flush()
                groups_by_name[group_name.lower()] = group

            resource = resource_model(name=name, group_id=group.id, site_id=site_id)
            session.add(resource)
            await session.flush()
            result.created += 1

        # Handle optional skill assignment
        if skill_name and attr_name and resource:
            skill = skills_by_name.get(skill_name.lower())
            if skill is None:
                skill = Skill(name=skill_name, resource_type=resource_type.value)
                session.add(skill)
                await session.flush()
                skills_by_name[skill_name.lower()] = skill

            attr_key = (skill.id, attr_name.lower())
            attribute = attrs_by_key.get(attr_key)
            if attribute is None:
                attribute = SkillAttribute(skill_id=skill.id, name=attr_name)
                session.add(attribute)
                await session.flush()
                attrs_by_key[attr_key] = attribute

            assign_key = (resource.id, attribute.id)
            if assign_key not in existing_assignments:
                session.add(
                    skill_model(
                        resource_id=resource.id, skill_attribute_id=attribute.id
                    )
                )
                existing_assignments.add(assign_key)

    await session.commit()
    return result


def _parse_header(row: tuple) -> list[str]:
    """Parse header row into cleaned strings."""
    return [str(cell).strip() if cell else "" for cell in row]


#: Header spellings that name the site column.
#:
#: Both languages, because the in-app help documents German column names and hand-built files exist —
#: the same reason ``shape.py`` accepts "Gruppe" beside "Group". The ASCII form is here because a CSV
#: round-trip through a mis-encoded editor turns "Betriebsstätte" into "Betriebsstaette", and refusing
#: that file would blame the operator for their spreadsheet's encoding.
_SITE_HEADERS = frozenset({"site", "betriebsstätte", "betriebsstaette", "standort"})


def _site_column_index(header: list[str]) -> int | None:
    """Position of the site column in a parsed header, or None when the file has none.

    BY NAME, not by position, and that is the whole point. The row loop reads Name/Group/Skill/
    Attribute as indices 0..3, so a site column wedged in anywhere before index 4 would otherwise be
    read as a skill. Locating it by header also means a file whose columns were reordered by hand
    still imports, and — the case that actually matters — a file exported before this column existed
    has no site header at all, which must mean "this file says nothing about sites" rather than
    "clear every site".
    """
    for index, cell in enumerate(header):
        if cell.strip().lower() in _SITE_HEADERS:
            return index
    return None


def resolve_site(
    name: str, sites_by_name: dict[str, Any]
) -> tuple[Any | None, str | None]:
    """Resolve a site NAME to its id, or explain why it cannot be resolved.

    ``sites_by_name`` is keyed by the site's REAL name; matching is case-insensitive internally. The
    keys are not pre-lowercased by the caller on purpose: this function quotes them back at the
    operator, and showing "werk ammendorf" next to their "Werk Amendorf" would ask them to spot a
    typo in text we mangled ourselves.

    Returns ``(site_id, error)``. Exactly one is meaningful: an empty name yields ``(None, None)``,
    which CLEARS the site and is not an error.

    An unknown name is REFUSED. This deliberately differs from ``ResourceGroup``, which this importer
    auto-creates a few lines below — and the difference is not squeamishness about typos. A site owns
    a holiday calendar: creating "Werk Amendorf" from a missing letter would produce a second plant
    with NO holidays, and every resource that landed there would silently lose the calendar its
    capacity arithmetic depends on. A redundant group is untidy; a resource under an empty holiday
    calendar is a plan that is wrong without saying so. Sites are also few and created once, so
    requiring them to exist first costs the operator almost nothing.
    """
    if not name.strip():
        return None, None
    wanted = name.strip().lower()
    for real_name, site_id in sites_by_name.items():
        if real_name.strip().lower() == wanted:
            return site_id, None
    known = ", ".join(sorted(sites_by_name.keys())) or "none defined yet"
    return None, (
        f"Unknown site {name.strip()!r}. Sites are not created on import, because a mistyped "
        f"name would produce a plant with no holiday calendar. Create it first under "
        f"Working time, then re-import. Known sites: {known}."
    )
