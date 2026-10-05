"""Router for unified import/export of personnel, infrastructure, projects, and templates.

Complete CSV files are shared between existing pages and the all-data ZIP.
Legacy flat CSV/Excel imports and Excel reports remain available.
"""

import asyncio
import csv
import io
from collections.abc import Iterable
from itertools import islice
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
    export_infrastructure_matrix_xlsx,
    export_infrastructure_xlsx,
    export_personnel_matrix_xlsx,
    export_personnel_xlsx,
    export_projects_xlsx,
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
    require_admin,
)

router = APIRouter(tags=["Import/Export"])


@router.get(
    "/migration/export", summary="Export complete migration as a CSV ZIP package"
)
async def export_migration_endpoint(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_admin),
):
    """Download planning, administration and history as versioned CSVs (admin only).

    Credentials, identity-provider bindings, sessions, derived conflicts and
    maintenance-run state are excluded. The archive preserves stable entity IDs.
    """
    from app.services.import_export.csv_transfer import export_migration

    try:
        content = await export_migration(session)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=capado-csv.zip"},
    )


@router.post(
    "/migration/import",
    response_model=ImportResultResponse,
    summary="Restore a CSV migration package into an empty installation",
)
async def import_migration_endpoint(
    file: UploadFile = File(..., description="Complete Capado CSV ZIP package"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> ImportResultResponse:
    """Validate and atomically restore every CSV with no manual import ordering.

    The destination may contain its bootstrap administrator, settings and audit
    records, but must contain no planning/master data. Keep that administrator's
    credentials; other accounts require password reset or identity relinking.
    Mail/scheduled maintenance stay disabled until explicitly configured again.
    """
    from app.services.import_export.csv_transfer import (
        MAX_ARCHIVE_BYTES,
        import_migration,
    )

    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(
            status_code=400, detail="Choose the complete Capado CSV ZIP package."
        )
    content = await file.read(MAX_ARCHIVE_BYTES + 1)
    if len(content) > MAX_ARCHIVE_BYTES:
        raise HTTPException(
            status_code=413, detail="CSV migration exceeds the 50 MiB archive limit."
        )
    result = await import_migration(session, content, current_user.id)
    return _result_to_dict(result, atomic=True)


@router.get("/data/{area}/export", summary="Export a complete CSV data area")
async def export_area_endpoint(
    area: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Download exactly the area CSV contained in the all-data ZIP."""
    from app.services.import_export import AREA_BY_NAME
    from app.services.import_export.csv_transfer import export_area

    if area not in AREA_BY_NAME:
        raise HTTPException(status_code=404, detail="Unknown CSV data area.")
    if area in {"administration", "history"}:
        check_write_permission(current_user, EntityType.bulk_import)
    try:
        content = await export_area(session, area)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={area}.csv"},
    )


@router.post(
    "/data/{area}/import",
    response_model=ImportResultResponse,
    summary="Atomically import a complete CSV data area",
)
async def import_area_endpoint(
    area: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> ImportResultResponse:
    """Insert/update by stable ID; validate external references against the target."""
    from app.services.import_export import AREA_BY_NAME
    from app.services.import_export.csv_transfer import import_area_rows

    if area not in AREA_BY_NAME:
        raise HTTPException(status_code=404, detail="Unknown CSV data area.")
    rows = await _parse_upload(file)
    return _result_to_dict(
        await import_area_rows(session, area, rows, current_user.id), atomic=True
    )


#: Named once because it appears six times and a typo in one of them produces a download that the
#: browser saves with the right extension and Excel then refuses to open.
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Bound both the upload and the parsed rows before an admin import can exhaust the backend.
_MAX_IMPORT_BYTES = 20 * 1024 * 1024
_MAX_IMPORT_ROWS = 10_000  # Includes the header row.


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
    """Download complete personnel CSVs or active-personnel Excel reports.

    Formats:
    - ``xlsx``: Skill matrix (resources as rows, skill/attributes as columns,
      two-row merged header grouping attributes under their skill). A REPORT —
      it cannot be imported back, because its header spans two rows.
    - ``xlsx-flat``: Flat list (Name, Group, Skill, Attribute) as a workbook.
      Editable in Excel AND re-importable.
    - ``csv``: Complete versioned area, including inactive resources, group
      hierarchy, qualifications and resource-specific working time; shared with ZIP.

    Args:
        format: Export format — 'xlsx', 'xlsx-flat', or 'csv'.
        session: Database session.

    Returns:
        File download response with personnel data.

    Raises:
        HTTPException: 400 when the format is not one of the three above.

    """
    if format == "csv":
        return await export_area_endpoint("personnel", session, _current_user)
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
    from app.services.import_export.csv_format import is_area_csv
    from app.services.import_export.csv_transfer import import_area_rows

    if is_area_csv(rows):
        result = await import_area_rows(session, "personnel", rows, current_user.id)
        return _result_to_dict(result, atomic=True)
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
    """Download complete infrastructure CSVs or active-resource Excel reports.

    Formats:
    - ``xlsx``: Skill matrix (resources as rows, skill/attributes as columns,
      two-row merged header grouping attributes under their skill). A REPORT —
      it cannot be imported back, because its header spans two rows.
    - ``xlsx-flat``: Flat list (Name, Group, Skill, Attribute) as a workbook.
      Editable in Excel AND re-importable — the combination the matrix cannot offer.
    - ``csv``: Complete versioned area, including inactive resources, group
      hierarchy, qualifications and resource-specific working time; shared with ZIP.

    Args:
        format: Export format — 'xlsx', 'xlsx-flat', or 'csv'.
        session: Database session.

    Returns:
        File download response with infrastructure data.

    Raises:
        HTTPException: 400 when the format is not one of the three above.

    """
    if format == "csv":
        return await export_area_endpoint("infrastructure", session, _current_user)
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
    from app.services.import_export.csv_format import is_area_csv
    from app.services.import_export.csv_transfer import import_area_rows

    if is_area_csv(rows):
        result = await import_area_rows(
            session, "infrastructure", rows, current_user.id
        )
        return _result_to_dict(result, atomic=True)
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

    CSV preserves all project-area fields and IDs through the shared area export.
    Excel retains its report columns: Project, dates, Work Package, Skill, Attribute, Quantity.

    Args:
        format: Export format, either 'xlsx' or 'csv'.
        session: Database session.

    Returns:
        File download response with project data.
    """
    if format == "csv":
        return await export_area_endpoint("projects", session, _current_user)
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
    from app.services.import_export.csv_format import is_area_csv
    from app.services.import_export.csv_transfer import import_area_rows

    if is_area_csv(rows):
        result = await import_area_rows(session, "projects", rows, current_user.id)
        return _result_to_dict(result, atomic=True)
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

    CSV preserves the complete template area and IDs; Excel retains the flat
    Template, Description, Skill, Attribute, Quantity report.

    Args:
        format: Export format, either 'xlsx' or 'csv'.
        session: Database session.

    Returns:
        File download response with template data.
    """
    if format == "csv":
        return await export_area_endpoint("templates", session, _current_user)
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

    CSV preserves the complete template area and IDs; Excel retains the flat
    Template, Description, Skill, Attribute, Quantity report.
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
    from app.services.import_export.csv_format import is_area_csv
    from app.services.import_export.csv_transfer import import_area_rows

    if is_area_csv(rows):
        result = await import_area_rows(session, "templates", rows, current_user.id)
        return _result_to_dict(result, atomic=True)
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

    The same complete area CSV as in the ZIP, including original booking IDs,
    dates/fractional allocations and UTC instants including subsecond precision.

    Args:
        session: Database session.

    Returns:
        CSV file download with assignment data.
    """
    return await export_area_endpoint("assignments", session, _current_user)


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

    New CSVs preserve IDs and all assignment fields through the shared area importer.
    Legacy flat files include Resource Type and Resource Group to qualify names.
    Legacy five/six-column files are accepted only with unambiguous references.
    Without Work Package, exactly one overlapping (or one total) work package
    must exist. Only identical intervals and allocations are skipped.

    Personnel use ISO dates. Infrastructure accepts offset-bearing ISO
    timestamps; legacy date-only values retain the 06:00/18:00 planning-zone defaults.

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
    from app.services.import_export.csv_format import is_area_csv
    from app.services.import_export.csv_transfer import import_area_rows

    if is_area_csv(rows):
        result = await import_area_rows(session, "assignments", rows, current_user.id)
        return _result_to_dict(result, atomic=True)
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
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".csv")):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{filename or 'unnamed'}'. Upload a .xlsx or .csv file — "
                "use the 'Excel (flat)' or CSV export to get one in the expected shape."
            ),
        )

    content = await file.read(_MAX_IMPORT_BYTES + 1)
    from app.services.import_export.csv_format import MAX_EXPANDED_BYTES

    canonical = filename.endswith(".csv") and content.removeprefix(
        b"\xef\xbb\xbf"
    ).startswith(b"Capado CSV;")
    if canonical:
        content += await file.read(MAX_EXPANDED_BYTES + 1 - len(content))
        if len(content) > MAX_EXPANDED_BYTES:
            raise HTTPException(
                status_code=413, detail="CSV imports must not exceed 100 MiB."
            )
    if not canonical and len(content) > _MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=413, detail="Import files must not exceed 20 MiB."
        )

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


def _limited_rows(rows: Iterable[tuple]) -> list[tuple]:
    """Materialize no more than the supported number of import rows."""
    result = list(islice(rows, _MAX_IMPORT_ROWS + 1))
    if len(result) > _MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=413, detail="Imports must not exceed 10,000 rows."
        )
    return result


def _parse_xlsx(content: bytes) -> list[tuple]:
    """Parse Excel content into row tuples (CPU-bound, runs in thread pool)."""
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = wb.active
        return _limited_rows(ws.iter_rows(values_only=True))
    finally:
        wb.close()


def _parse_csv(content: bytes) -> list[tuple]:
    """Parse CSV content into row tuples (CPU-bound, runs in thread pool)."""
    from app.services.import_export.csv_format import _read_csv

    if content.removeprefix(b"\xef\xbb\xbf").startswith(b"Capado CSV;"):
        try:
            return [tuple(row) for row in _read_csv(content)]
        except (ValueError, csv.Error) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    text = content.decode("utf-8-sig")
    delimiter = ";" if ";" in text.split("\n")[0] else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return _limited_rows(tuple(row) for row in reader)


def _result_to_dict(
    result: ImportResult, *, atomic: bool = False
) -> ImportResultResponse:
    """Convert ImportResult to a response model."""
    return ImportResultResponse(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.errors,
        success=len(result.errors) == 0,
        atomic=atomic,
        conflicts_found=result.conflicts_found,
        conflict_check_failed=result.conflict_check_failed,
    )
