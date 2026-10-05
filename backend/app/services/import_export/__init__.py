"""Public import/export API and the explicitly ordered complete CSV domains."""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from . import (
    absences,
    administration,
    assignments,
    history,
    infrastructure,
    personnel,
    projects,
    skills,
    templates,
    working_time,
)
from .assignments import export_assignments_csv, import_assignments
from .common import ImportResult
from .csv_format import CsvArea, CsvBatch
from .csv_storage import ImportContext
from .infrastructure import (
    export_infrastructure_csv,
    export_infrastructure_matrix_xlsx,
    export_infrastructure_xlsx,
    import_infrastructure,
)
from .personnel import (
    export_personnel_csv,
    export_personnel_matrix_xlsx,
    export_personnel_xlsx,
    import_personnel,
)
from .projects import (
    export_projects_csv,
    export_projects_xlsx,
    import_projects,
)
from .templates import (
    export_templates_csv,
    export_templates_xlsx,
    import_templates,
)


class CsvDomain(Protocol):
    """Static interface implemented by ordinary domain module functions."""

    CSV_AREA: CsvArea

    async def load_export(self, session: AsyncSession) -> dict[str, list[dict]]:
        """Load approved rows and public export references."""
        ...

    def export_csv(self, data: dict[str, list[dict]]) -> bytes:
        """Serialize this domain's complete CSV."""
        ...

    def parse_csv(self, rows: list[tuple] | list[list[str]]) -> CsvBatch:
        """Decode and check domain ownership."""
        ...

    def validate_import(self, context: ImportContext) -> None:
        """Check the planned final state before any writes."""
        ...

    async def write_import(
        self, session: AsyncSession, batch: CsvBatch, context: ImportContext
    ) -> ImportResult:
        """Apply approved rows without committing."""
        ...


# Fixed order mirrors the manual CSV dependency order; no module discovery.
CSV_DOMAINS: tuple[CsvDomain, ...] = (
    working_time,
    skills,
    personnel,
    infrastructure,
    projects,
    templates,
    assignments,
    absences,
    administration,
    history,
)
DOMAIN_BY_NAME = {domain.CSV_AREA.name: domain for domain in CSV_DOMAINS}
AREAS = tuple(domain.CSV_AREA for domain in CSV_DOMAINS)
AREA_BY_NAME = {area.name: area for area in AREAS}
ENTITIES = tuple(
    {entity.name: entity for area in AREAS for entity in area.entities}.values()
)
EXCLUDED_TABLES = {
    "refresh_tokens",
    "conflicts",
    "conflict_assignments",
    "scheduled_job_runs",
}


__all__ = [
    "ImportResult",
    "export_assignments_csv",
    "export_infrastructure_csv",
    "export_infrastructure_matrix_xlsx",
    "export_infrastructure_xlsx",
    "export_personnel_csv",
    "export_personnel_matrix_xlsx",
    "export_personnel_xlsx",
    "export_projects_csv",
    "export_projects_xlsx",
    "export_templates_csv",
    "export_templates_xlsx",
    "import_assignments",
    "import_infrastructure",
    "import_personnel",
    "import_projects",
    "import_templates",
]
