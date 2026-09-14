"""Permission dependencies for FastAPI: authentication and authorization.

Provides centralized permission checking as FastAPI dependencies:
- get_current_user: decode JWT, load user, check is_active
- require_admin: 403 if user is not admin
- check_write_permission: scope-based authorization per entity type

The scope model is unified: editors have a list of group_ids they can manage.
Both personal and infrastructure resources belong to a group. The permission
check verifies the resource's group_id is in the user's scope_group_ids.
"""

from enum import StrEnum
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.exceptions import BusinessRuleError
from app.models.user import User, UserRole
from app.services.audit import set_actor
from app.services.auth_service import decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


class EntityType(StrEnum):
    """Entity types used for write permission scope checks.

    ``skill`` and ``global_definition`` look similar and are deliberately separate. A skill
    ASSIGNMENT belongs to one resource and therefore to one group, so an editor may write it
    within their scope. A skill DEFINITION — the skill itself, its attributes, and the work
    package templates built from them — is global: it has no group, so there is no scope that
    could contain it.

    Conflating the two is what made this distinction worth naming. A global definition passed
    through the group-scoped branch reaches ``group_id is None`` and denies every editor, which
    is the correct outcome arrived at by accident — and an accident reads like a bug to the next
    person, who fixes it and silently widens access.
    """

    resource = "resource"
    assignment = "assignment"
    skill = "skill"
    global_definition = "global_definition"
    bulk_import = "bulk_import"
    project = "project"
    work_package = "work_package"
    user_management = "user_management"


async def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Return the authenticated user without the password-change gate.

    Decodes the JWT from the Authorization header, loads the user from the
    database, and verifies the account is active. This variant does NOT block
    users flagged with ``must_change_password`` and is intended only for the
    change-password endpoint. All other endpoints should depend on
    :func:`get_current_user`, which enforces the password change.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except BusinessRuleError as exc:
        detail = (
            "Token expired" if "expired" in str(exc).lower() else "Not authenticated"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    statement = select(User).where(User.id == UUID(user_id))
    result = await session.execute(statement)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Every authenticated write on this session is attributable from here on.
    # Stamped once, at the single point every authenticated request passes
    # through, so no service signature has to carry an actor (ADR-006).
    set_actor(session, user.id)

    return user


async def get_current_user(
    user: User = Depends(get_authenticated_user),
) -> User:
    """FastAPI dependency that returns the authenticated, unrestricted user.

    Builds on :func:`get_authenticated_user` and additionally rejects users
    who must change their password (HTTP 403), forcing them through the
    change-password flow before any other API access.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required",
            headers={"X-Error-Code": "password_change_required"},
        )
    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency that requires the current user to be an admin."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
            headers={"X-Error-Code": "insufficient_role"},
        )
    return current_user


def check_write_permission(
    user: User,
    entity_type: EntityType,
    *,
    group_id: UUID | None = None,
    project_id: UUID | None = None,
) -> None:
    """Check whether a user has write permission for a given entity.

    Unified scope model:
    - Admin: bypasses all checks.
    - Viewer: always denied.
    - Editor: allowed if the entity's group_id is in scope_group_ids,
      or the project_id is in scope_project_ids.
    - Editor on a global definition: always denied, because a global entity has no group
      and renaming one silently redefines what every existing requirement means.

    Args:
        user: The authenticated user.
        entity_type: The type of entity being written to.
        group_id: The group of the resource (for resources, assignments, skill assignments).
        project_id: The project ID (for projects/work packages).

    Raises:
        HTTPException: 403 if permission is denied.

    """
    # Admin bypasses all checks
    if user.role == UserRole.admin:
        return

    # Viewer cannot write anything
    if user.role == UserRole.viewer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
            headers={"X-Error-Code": "insufficient_role"},
        )

    # Editor — check scopes.
    #
    # Admin-only regardless of scope. User management is obvious; the other two are not, so the
    # reasons are recorded here rather than left to be re-derived.
    #
    # Global definitions — skills, their attributes and the templates built from them — are
    # referenced by UUID, so renaming one breaks no data. It REDEFINES every requirement already
    # pointing at it, across every group, with no error and no conflict raised. That is a
    # plant-wide semantic change, and a group-scoped role cannot judge it. It also invalidates
    # stored import files, which resolve skills by name.
    #
    # Bulk imports cannot be scope-checked at all: the uploaded file may name resources in any
    # group, so there is no single group_id that could authorise it — the scope is only knowable
    # after parsing, at which point the check is decoration. The personnel and infrastructure
    # importers additionally auto-create missing skills and attributes, which is a global-catalogue
    # write, so allowing an editor here would reopen exactly what global_definition closes.
    if entity_type in (
        EntityType.user_management,
        EntityType.global_definition,
        EntityType.bulk_import,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
            headers={"X-Error-Code": "insufficient_role"},
        )

    if entity_type in (
        EntityType.resource,
        EntityType.assignment,
        EntityType.skill,
    ):
        if group_id is None or group_id not in (user.scope_group_ids or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Resource not in your scope",
                headers={"X-Error-Code": "out_of_scope"},
            )
        return

    if entity_type in (
        EntityType.project,
        EntityType.work_package,
    ):
        if project_id is None or project_id not in (user.scope_project_ids or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Resource not in your scope",
                headers={"X-Error-Code": "out_of_scope"},
            )
        return

    # Unknown entity type — deny by default
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
        headers={"X-Error-Code": "insufficient_role"},
    )
