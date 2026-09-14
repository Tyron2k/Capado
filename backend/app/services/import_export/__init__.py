"""Unified import/export service for personnel, infrastructure, and projects.

Each resource type exports/imports with optional Skill and Attribute columns
so that resource definitions and their skill assignments live in a single file.
Projects include optional Skill, Attribute, and Quantity columns for work package
requirements.

This package splits the former ``import_export_service`` module into one
module per domain (personnel, infrastructure, projects, templates,
assignments) plus a ``common`` module for shared helpers. The public API is
re-exported here so callers can import from ``app.services.import_export``.
"""

from .assignments import export_assignments_csv, import_assignments
from .common import ImportResult
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
