"""SQLModel table definitions re-exported for Alembic autogenerate discovery."""

from app.models.absence import Absence, AbsenceReason  # noqa: F401
from app.models.assignment import Assignment  # noqa: F401
from app.models.audit import AuditAction, AuditLog  # noqa: F401
from app.models.baseline import Baseline, BaselineEntry  # noqa: F401
from app.models.calendar import (  # noqa: F401
    Holiday,
    InfrastructureAvailabilityWindow,
    ResourceWorkProfile,
    WorkWeekProfile,
)
from app.models.conflict import (  # noqa: F401
    Conflict,
    ConflictAssignment,
    ConflictCause,
)
from app.models.customer import Customer  # noqa: F401
from app.models.organization_settings import OrganizationSettings  # noqa: F401
from app.models.project import Project, WorkPackage  # noqa: F401
from app.models.resource import (  # noqa: F401
    InfrastructureResource,
    PersonalResource,
    ResourceType,
)
from app.models.resource_group import ResourceGroup  # noqa: F401
from app.models.scheduled_job_run import (  # noqa: F401
    JobRunStatus,
    ScheduledJobRun,
)
from app.models.site import Site  # noqa: F401
from app.models.skill import (  # noqa: F401
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    Skill,
    SkillAttribute,
)
from app.models.user import RefreshToken, User, UserRole  # noqa: F401
from app.models.work_package_requirement import WorkPackageRequirement  # noqa: F401
from app.models.work_package_template import (  # noqa: F401
    WorkPackageTemplate,
    WorkPackageTemplateRequirement,
)

__all__ = [
    "ResourceType",
    "PersonalResource",
    "InfrastructureResource",
    "ResourceGroup",
    "Site",
    "Holiday",
    "WorkWeekProfile",
    "ResourceWorkProfile",
    "InfrastructureAvailabilityWindow",
    "Project",
    "WorkPackage",
    "Assignment",
    "AuditLog",
    "AuditAction",
    "Baseline",
    "BaselineEntry",
    "Conflict",
    "ConflictAssignment",
    "ConflictCause",
    "Skill",
    "SkillAttribute",
    "PersonalResourceSkill",
    "InfrastructureResourceSkill",
    "User",
    "UserRole",
    "RefreshToken",
    "OrganizationSettings",
    "WorkPackageRequirement",
    "WorkPackageTemplate",
    "WorkPackageTemplateRequirement",
]
