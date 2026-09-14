"""Router for unified import/export of personnel, infrastructure, projects, and templates.

Each resource type supports both Excel (.xlsx) and CSV (.csv) for upload and download.
Personnel and infrastructure exports include skill assignments inline.
Project exports include work package requirements inline.
"""

import asyncio
import csv
import io
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.import_export import ImportResultResponse
from app.services.import_export import (
    ImportResult,
    export_assignments_csv,
    export_infrastructure_csv,
    export_infrastructure_matrix_xlsx,
    export_infrastructure_xlsx,
    export_personnel_csv,
    export_personnel_matrix_xlsx,
    export_personnel_xlsx,
    export_projects_csv,
    export_projects_xlsx,
    export_templates_csv,
    export_templates_xlsx,
    import_assignments,
    import_infrastructure,
    import_personnel,
    import_projects,
    import_templates,
)
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)

router = APIRouter(tags=["Import/Export"])

#: Named once because it appears six times and a typo in one of them produces a download that the
#: browser saves with the right extension and Excel then refuses to open.
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ===========================================================================
# Personnel
# ===========================================================================


@router.get("/personnel/export", summary="Export personnel as Excel or CSV")
async def export_personnel_endpoint(
    format: str = Query(
        default="xlsx", description="Export format: xlsx (matrix), xlsx-flat, or csv"
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Download all active personal resources with skill assignments.

    Formats:
    - ``xlsx``: Skill matrix (resources as rows, skill/attributes as columns,
      two-row merged header grouping attributes under their skill). A REPORT —
      it cannot be imported back, because its header spans two rows.
    - ``xlsx-flat``: Flat list (Name, Group, Skill, Attribute) as a workbook.
      Editable in Excel AND re-importable.
    - ``csv``: Same flat list as CSV.

    Args:
        format: Export format — 'xlsx', 'xlsx-flat', or 'csv'.
        session: Database session.

    Returns:
        File download response with personnel data.

    Raises:
        HTTPException: 400 when the format is not one of the three above.

    """
    if format == "csv":
        content = await export_personnel_csv(session)
        return Response(
            content=content.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=personnel.csv"},
        )
    if format == "xlsx-flat":
        data = await export_personnel_xlsx(session)
        return Response(
            content=data,
            media_type=_XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": "attachment; filename=personnel-flat.xlsx"},
        )
    if format != "xlsx":
        raise HTTPException(
            status_code=400,
            detail=f"Unknown export format '{format}'. Use 'xlsx', 'xlsx-flat', or 'csv'.",
        )
    data = await export_personnel_matrix_xlsx(session)
    return Response(
        content=data,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=personnel.xlsx"},
    )


@router.post(
    "/personnel/import",
    response_model=ImportResultResponse,
    summary="Import personnel from Excel or CSV",
)
async def import_personnel_endpoint(
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ImportResultResponse:
    """Upload personnel data with optional skill assignments.

    Required columns: Name, Group.
    Optional columns: Skill, Attribute (auto-creates skills if missing).
    Admin only: the file may name resources in any group, so no scope can authorise it.

    Args:
        file: Excel (.xlsx) or CSV (.csv) file with personnel data.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        Import result with counts of created, updated, and skipped records.
    """
    check_write_permission(current_user, EntityType.bulk_import)
    rows = await _parse_upload(file)
    result = await import_personnel(session, rows)
    return _result_to_dict(result)


# ===========================================================================
# Infrastructure
# ===========================================================================


@router.get("/infrastructure/export", summary="Export infrastructure as Excel or CSV")
async def export_infrastructure_endpoint(
    format: str = Query(
        default="xlsx", description="Export format: xlsx (matrix), xlsx-flat, or csv"
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Download all active infrastructure resources with skill assignments.

    Formats:
    - ``xlsx``: Skill matrix (resources as rows, skill/attributes as columns,
      two-row merged header grouping attributes under their skill). A REPORT —
      it cannot be imported back, because its header spans two rows.
    - ``xlsx-flat``: Flat list (Name, Group, Skill, Attribute) as a workbook.
      Editable in Excel AND re-importable — the combination the matrix cannot offer.
    - ``csv``: Same flat list as CSV.

    Args:
        format: Export format — 'xlsx', 'xlsx-flat', or 'csv'.
        session: Database session.

    Returns:
        File download response with infrastructure data.

    Raises:
        HTTPException: 400 when the format is not one of the three above.

    """
    if format == "csv":
        content = await export_infrastructure_csv(session)
        return Response(
            content=content.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=infrastructure.csv"},
        )
    if format == "xlsx-flat":
        data = await export_infrastructure_xlsx(session)
        return Response(
            content=data,
            media_type=_XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": "attachment; filename=infrastructure-flat.xlsx"
            },
        )
    # An unknown value used to fall through to the matrix silently, so a typo handed back a file
    # that looked right and could not be imported. Naming it is cheaper than that confusion.
    if format != "xlsx":
        raise HTTPException(
            status_code=400,
            detail=f"Unknown export format '{format}'. Use 'xlsx', 'xlsx-flat', or 'csv'.",
        )
    data = await export_infrastructure_matrix_xlsx(session)
    return Response(
        content=data,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=infrastructure.xlsx"},
    )


@router.post(
    "/infrastructure/import",
    response_model=ImportResultResponse,
    summary="Import infrastructure from Excel or CSV",
)
async def import_infrastructure_endpoint(
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ImportResultResponse:
    """Upload infrastructure data with optional skill assignments.

    Required columns: Name, Group.
    Optional columns: Skill, Attribute (auto-creates skills if missing).
    Admin only: the file may name resources in any group, so no scope can authorise it.

    Args:
        file: Excel (.xlsx) or CSV (.csv) file with infrastructure data.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        Import result with counts of created, updated, and skipped records.
    """
    check_write_permission(current_user, EntityType.bulk_import)
    rows = await _parse_upload(file)
    result = await import_infrastructure(session, rows)
    return _result_to_dict(result)


# ===========================================================================
# Projects
# ===========================================================================


@router.get("/projects/export", summary="Export projects and work packages")
async def export_projects_endpoint(
    format: str = Query(default="xlsx", description="Export format: xlsx or csv"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Download all projects with work packages and requirements as Excel or CSV.

    Format: Project; Project Start; Project End; Work Package; WP Start; WP End;
    Skill; Attribute; Quantity.

    Args:
        format: Export format, either 'xlsx' or 'csv'.
        session: Database session.

    Returns:
        File download response with project data.
    """
    if format == "csv":
        content = await export_projects_csv(session)
        return Response(
            content=content.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=projects.csv"},
        )
    data = await export_projects_xlsx(session)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=projects.xlsx"},
    )


@router.post(
    "/projects/import",
    response_model=ImportResultResponse,
    summary="Import projects and work packages from Excel or CSV",
)
async def import_projects_endpoint(
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ImportResultResponse:
    """Upload project data with optional work package requirements.

    Required columns: Project, Project Start, Project End.
    Admin only: the file may name resources in any group, so no scope can authorise it.
    Optional: Work Package, WP Start, WP End, Skill, Attribute, Quantity.
    Skills must already exist. Dates in ISO format (YYYY-MM-DD).

    Args:
        file: Excel (.xlsx) or CSV (.csv) file with project data.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        Import result with counts of created, updated, and skipped records.
    """
    check_write_permission(current_user, EntityType.bulk_import)
    rows = await _parse_upload(file)
    result = await import_projects(session, rows)
    return _result_to_dict(result)


# ===========================================================================
# Templates
# ===========================================================================


@router.get("/templates/export", summary="Export templates and requirements")
async def export_templates_endpoint(
    format: str = Query(default="xlsx", description="Export format: xlsx or csv"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Download all templates with their skill requirements as Excel or CSV.

    Format: Template; Description; Skill; Attribute; Quantity.

    Args:
        format: Export format, either 'xlsx' or 'csv'.
        session: Database session.

    Returns:
        File download response with template data.
    """
    if format == "csv":
        content = await export_templates_csv(session)
        return Response(
            content=content.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=templates.csv"},
        )
    data = await export_templates_xlsx(session)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=templates.xlsx"},
    )


@router.post(
    "/templates/import",
    response_model=ImportResultResponse,
    summary="Import templates and requirements from Excel or CSV",
)
async def import_templates_endpoint(
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ImportResultResponse:
    """Upload template data and create or update templates matched by name.

    Format: Template; Description; Skill; Attribute; Quantity.
    Skills and attributes must already exist.
    Admin only: the file may name resources in any group, so no scope can authorise it.

    Args:
        file: Excel (.xlsx) or CSV (.csv) file with template data.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        Import result with counts of created, updated, and skipped records.
    """
    check_write_permission(current_user, EntityType.bulk_import)
    rows = await _parse_upload(file)
    result = await import_templates(session, rows)
    return _result_to_dict(result)


# ===========================================================================
# Assignments
# ===========================================================================


@router.get("/assignments/export", summary="Export assignments as CSV")
async def export_assignments_endpoint(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Download all assignments as CSV.

    Format: Project; Work Package; Resource; Start; End; Allocation.
    Includes both personal and infrastructure assignments.

    Args:
        session: Database session.

    Returns:
        CSV file download with assignment data.
    """
    content = await export_assignments_csv(session)
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=assignments.csv"},
    )


@router.post(
    "/assignments/import",
    response_model=ImportResultResponse,
    summary="Import assignments from Excel or CSV",
)
async def import_assignments_endpoint(
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ImportResultResponse:
    """Upload assignment data to create resource-to-work-package assignments.

    Supports two CSV column formats:
    - 5 columns: Project; Resource; Start; End; Allocation
    - 6 columns: Project; Work Package; Resource; Start; End; Allocation

    In 5-column mode the work package is auto-resolved by finding the first
    WP in the project whose date range overlaps the assignment dates.

    Resources are resolved by name — if found as infrastructure, an
    infrastructure assignment is created; if found as personal, a personal
    assignment is created. Duplicates (same resource + work package) are
    skipped. Dates must be in ISO format (YYYY-MM-DD).

    Admin only: the file may name resources in any group, so no scope can authorise it.

    Args:
        file: Excel (.xlsx) or CSV (.csv) file with assignment data.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        Import result with counts of created, skipped, and errored records.
    """
    check_write_permission(current_user, EntityType.bulk_import)
    rows = await _parse_upload(file)
    result = await import_assignments(session, rows)
    return _result_to_dict(result)


# ===========================================================================
# Helpers
# ===========================================================================


async def _parse_upload(file: UploadFile) -> list[tuple]:
    """Parse an uploaded file (xlsx or csv) into a list of row tuples.

    Both Excel and CSV parsing are offloaded to a thread pool to avoid
    blocking the async event loop with CPU-bound work.

    The extension is REQUIRED rather than guessed. The previous version tried Excel and fell back to
    CSV for anything unrecognised, so a .pdf or a .xls became "could not read the header" three layers
    down — a message about the content of a file that was never the right kind. Refusing by extension
    puts the complaint where the mistake is.

    Raises:
        HTTPException: 400 when the extension is neither .xlsx nor .csv, or the file cannot be read
            as the kind its name claims.

    """
    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".xlsx"):
        try:
            return await asyncio.to_thread(_parse_xlsx, content)
        except (InvalidFileException, BadZipFile, KeyError) as exc:
            # Named .xlsx but not a workbook — most often a .xls renamed, or a CSV renamed.
            raise HTTPException(
                status_code=400,
                detail=(
                    "The file is named .xlsx but could not be read as an Excel workbook. "
                    "If it came from an older Excel, save it as .xlsx or export as CSV."
                ),
            ) from exc
    if filename.endswith(".csv"):
        try:
            return await asyncio.to_thread(_parse_csv, content)
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The CSV could not be read as UTF-8. Save it from Excel as "
                    "'CSV UTF-8 (comma delimited)'."
                ),
            ) from exc
    raise HTTPException(
        status_code=400,
        detail=(
            f"Unsupported file type '{filename or 'unnamed'}'. Upload a .xlsx or .csv file — "
            "use the 'Excel (flat)' or CSV export to get one in the expected shape."
        ),
    )


def _parse_xlsx(content: bytes) -> list[tuple]:
    """Parse Excel content into row tuples (CPU-bound, runs in thread pool)."""
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    return list(ws.iter_rows(values_only=True))


def _parse_csv(content: bytes) -> list[tuple]:
    """Parse CSV content into row tuples (CPU-bound, runs in thread pool)."""
    text = content.decode("utf-8-sig")
    delimiter = ";" if ";" in text.split("\n")[0] else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [tuple(row) for row in reader]


def _result_to_dict(result: ImportResult) -> ImportResultResponse:
    """Convert ImportResult to a response model."""
    return ImportResultResponse(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.errors,
        success=len(result.errors) == 0,
    )
