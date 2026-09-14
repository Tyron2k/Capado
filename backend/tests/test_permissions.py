"""Integration tests for app.services.permissions.

Covers:
- AUTH_ENABLED=false returns synthetic admin
- AUTH_ENABLED=true requires valid JWT
- get_current_user decodes JWT and loads user
- require_admin rejects non-admin users
- check_write_permission scope logic for all entity types and roles
"""

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.user import User, UserRole
from app.services.auth_service import create_access_token
from app.services.permissions import (
    EntityType,
    check_write_permission,
)


# Override the autouse database fixture — these tests use mocks, not a real DB.
@pytest.fixture(autouse=True)
def setup_database():
    """No-op override: permission tests don't need the test database."""
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    role: str = UserRole.editor,
    scope_group_ids: list[UUID] | None = None,
    scope_project_ids: list[UUID] | None = None,
    is_active: bool = True,
) -> User:
    """Create a test User instance with given role and scopes."""
    return User(
        id=uuid4(),
        email="test@example.com",
        name="Test User",
        password_hash="hashed",
        role=role,
        scope_group_ids=scope_group_ids,
        scope_project_ids=scope_project_ids,
        is_active=is_active,
        must_change_password=False,
    )


def _make_bearer(user: User) -> object:
    """Create a mock HTTPAuthorizationCredentials with a valid JWT for user."""
    token = create_access_token(
        user_id=user.id,
        role=user.role,
        scopes={
            "scope_group_ids": user.scope_group_ids,
            "scope_project_ids": user.scope_project_ids,
        },
    )

    class FakeCredentials:
        credentials = token

    return FakeCredentials()


# ---------------------------------------------------------------------------
# Authentication required (JWT validation)
# ---------------------------------------------------------------------------


class TestAuthRequired:
    """Tests for JWT-based authentication (get_authenticated_user)."""

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_401(self):
        """Missing Authorization header raises 401."""
        from app.services.permissions import get_authenticated_user

        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_user(credentials=None, session=AsyncMock())
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Not authenticated"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        """An invalid JWT raises 401."""
        from app.services.permissions import get_authenticated_user

        class FakeCredentials:
            credentials = "invalid-token"

        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_user(
                credentials=FakeCredentials(), session=AsyncMock()
            )
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Not authenticated"

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        """An expired JWT raises 401 with 'Token expired'."""
        from app.services.permissions import get_authenticated_user

        token = create_access_token(
            user_id=uuid4(),
            role="admin",
            scopes={},
            expires_delta=timedelta(seconds=-1),
        )

        class FakeCredentials:
            credentials = token

        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_user(
                credentials=FakeCredentials(), session=AsyncMock()
            )
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail in ("Token expired", "Not authenticated")

    @pytest.mark.asyncio
    async def test_valid_token_loads_user(self):
        """A valid JWT loads the user from the database."""
        from app.services.permissions import get_authenticated_user

        user = _make_user(role=UserRole.admin)
        credentials = _make_bearer(user)

        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = lambda: user
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await get_authenticated_user(
            credentials=credentials, session=mock_session
        )
        assert result.id == user.id
        assert result.role == UserRole.admin

    @pytest.mark.asyncio
    async def test_inactive_user_raises_401(self):
        """A deactivated user raises 401."""
        from app.services.permissions import get_authenticated_user

        user = _make_user(role=UserRole.admin, is_active=False)
        credentials = _make_bearer(user)

        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = lambda: user
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_user(credentials=credentials, session=mock_session)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Account deactivated"

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        """A valid JWT for a non-existent user raises 401."""
        from app.services.permissions import get_authenticated_user

        user = _make_user(role=UserRole.admin)
        credentials = _make_bearer(user)

        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = lambda: None
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_user(credentials=credentials, session=mock_session)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Not authenticated"


class TestPasswordChangeGate:
    """Tests for the must_change_password enforcement in get_current_user."""

    @pytest.mark.asyncio
    async def test_user_without_flag_passes(self):
        """A user who need not change their password passes the gate."""
        from app.services.permissions import get_current_user

        user = _make_user(role=UserRole.editor)
        user.must_change_password = False

        result = await get_current_user(user=user)
        assert result.id == user.id

    @pytest.mark.asyncio
    async def test_user_with_flag_blocked_403(self):
        """A user flagged must_change_password is blocked with 403."""
        from app.services.permissions import get_current_user

        user = _make_user(role=UserRole.editor)
        user.must_change_password = True

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(user=user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.headers["X-Error-Code"] == "password_change_required"


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    """Tests for the require_admin dependency."""

    @pytest.mark.asyncio
    async def test_admin_passes(self):
        """Admin user passes require_admin check."""
        from app.services.permissions import require_admin

        admin = _make_user(role=UserRole.admin)
        result = await require_admin(current_user=admin)
        assert result.role == UserRole.admin

    @pytest.mark.asyncio
    async def test_editor_rejected(self):
        """Editor user is rejected by require_admin."""
        from app.services.permissions import require_admin

        editor = _make_user(role=UserRole.editor)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user=editor)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Insufficient permissions"

    @pytest.mark.asyncio
    async def test_viewer_rejected(self):
        """Viewer user is rejected by require_admin."""
        from app.services.permissions import require_admin

        viewer = _make_user(role=UserRole.viewer)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user=viewer)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Insufficient permissions"


# ---------------------------------------------------------------------------
# check_write_permission — Admin bypass
# ---------------------------------------------------------------------------


class TestAdminBypass:
    """Tests that admin bypasses all permission checks."""

    def test_admin_can_write_resource(self):
        """Admin can write resources without scope."""
        admin = _make_user(role=UserRole.admin)
        check_write_permission(admin, EntityType.resource, group_id=uuid4())

    def test_admin_can_write_assignment(self):
        """Admin can write assignments without scope."""
        admin = _make_user(role=UserRole.admin)
        check_write_permission(admin, EntityType.assignment, group_id=uuid4())

    def test_admin_can_write_project(self):
        """Admin can write projects without scope."""
        admin = _make_user(role=UserRole.admin)
        check_write_permission(admin, EntityType.project, project_id=uuid4())

    def test_admin_can_write_skill(self):
        """Admin can write skills."""
        admin = _make_user(role=UserRole.admin)
        check_write_permission(admin, EntityType.skill, group_id=uuid4())

    def test_admin_can_manage_users(self):
        """Admin can manage users."""
        admin = _make_user(role=UserRole.admin)
        check_write_permission(admin, EntityType.user_management)


# ---------------------------------------------------------------------------
# check_write_permission — Viewer denied
# ---------------------------------------------------------------------------


class TestViewerDenied:
    """Tests that viewer is always denied write access."""

    def test_viewer_cannot_write_resource(self):
        """Viewer cannot write resources."""
        viewer = _make_user(role=UserRole.viewer)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(viewer, EntityType.resource, group_id=uuid4())
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Insufficient permissions"

    def test_viewer_cannot_write_assignment(self):
        """Viewer cannot write assignments."""
        viewer = _make_user(role=UserRole.viewer)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(viewer, EntityType.assignment, group_id=uuid4())
        assert exc_info.value.status_code == 403

    def test_viewer_cannot_write_project(self):
        """Viewer cannot write projects."""
        viewer = _make_user(role=UserRole.viewer)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(viewer, EntityType.project, project_id=uuid4())
        assert exc_info.value.status_code == 403

    def test_viewer_cannot_write_skill(self):
        """Viewer cannot write skills."""
        viewer = _make_user(role=UserRole.viewer)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(viewer, EntityType.skill, group_id=uuid4())
        assert exc_info.value.status_code == 403

    def test_viewer_cannot_manage_users(self):
        """Viewer cannot manage users."""
        viewer = _make_user(role=UserRole.viewer)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(viewer, EntityType.user_management)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# check_write_permission — Editor scope checks
# ---------------------------------------------------------------------------


class TestEditorScopes:
    """Tests for editor scope-based permission checks."""

    # --- Group scope ---

    def test_editor_with_matching_group_can_write_resource(self):
        """Editor with matching group_id can write resources."""
        group_id = uuid4()
        editor = _make_user(role=UserRole.editor, scope_group_ids=[group_id, uuid4()])
        check_write_permission(editor, EntityType.resource, group_id=group_id)

    def test_editor_without_matching_group_denied_resource(self):
        """Editor without matching group_id is denied."""
        editor = _make_user(role=UserRole.editor, scope_group_ids=[uuid4()])
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.resource, group_id=uuid4())
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Resource not in your scope"

    def test_editor_with_no_groups_denied_resource(self):
        """Editor with no group scopes is denied resources."""
        editor = _make_user(role=UserRole.editor, scope_group_ids=None)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.resource, group_id=uuid4())
        assert exc_info.value.status_code == 403

    def test_editor_group_scope_applies_to_assignments(self):
        """Group scope also applies to assignments."""
        group_id = uuid4()
        editor = _make_user(role=UserRole.editor, scope_group_ids=[group_id])
        check_write_permission(editor, EntityType.assignment, group_id=group_id)

    def test_editor_group_scope_applies_to_skills(self):
        """Group scope also applies to skills."""
        group_id = uuid4()
        editor = _make_user(role=UserRole.editor, scope_group_ids=[group_id])
        check_write_permission(editor, EntityType.skill, group_id=group_id)

    # --- Global definitions (skills themselves, attributes, work package templates) ---

    def test_admin_can_write_global_definition(self):
        """Admin manages the global catalogue."""
        admin = _make_user(role=UserRole.admin)
        check_write_permission(admin, EntityType.global_definition)

    def test_editor_cannot_write_global_definition(self):
        """An editor is denied the global catalogue."""
        editor = _make_user(role=UserRole.editor, scope_group_ids=[uuid4()])
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.global_definition)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Insufficient permissions"

    def test_editor_denied_global_definition_even_within_scope(self):
        """A group in scope does not help — this is the point of the separate entity type.

        A global definition has no group, so passing one cannot grant access. Were this to pass,
        an editor could rename a skill every other department's requirements point at.
        """
        group_id = uuid4()
        editor = _make_user(role=UserRole.editor, scope_group_ids=[group_id])
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(
                editor, EntityType.global_definition, group_id=group_id
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.headers["X-Error-Code"] == "insufficient_role"

    def test_viewer_cannot_write_global_definition(self):
        """A viewer is denied, as everywhere else."""
        viewer = _make_user(role=UserRole.viewer)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(viewer, EntityType.global_definition)
        assert exc_info.value.status_code == 403

    # --- Bulk imports ---

    def test_admin_can_bulk_import(self):
        """Admin may upload an import file."""
        admin = _make_user(role=UserRole.admin)
        check_write_permission(admin, EntityType.bulk_import)

    def test_editor_cannot_bulk_import_even_within_scope(self):
        """An editor is denied, and a group in scope does not help.

        An uploaded file may name resources in any group, so the scope is only knowable after
        parsing — at which point a permission check is decoration. The personnel and infrastructure
        importers also auto-create missing skills, which is a global-catalogue write.
        """
        group_id = uuid4()
        editor = _make_user(role=UserRole.editor, scope_group_ids=[group_id])
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.bulk_import, group_id=group_id)
        assert exc_info.value.status_code == 403
        assert exc_info.value.headers["X-Error-Code"] == "insufficient_role"

    # --- Project scope ---

    def test_editor_with_matching_project_can_write_project(self):
        """Editor with matching project ID can write projects."""
        project_id = uuid4()
        editor = _make_user(role=UserRole.editor, scope_project_ids=[project_id])
        check_write_permission(editor, EntityType.project, project_id=project_id)

    def test_editor_without_matching_project_denied(self):
        """Editor without matching project ID is denied."""
        editor = _make_user(role=UserRole.editor, scope_project_ids=[uuid4()])
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.project, project_id=uuid4())
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Resource not in your scope"

    def test_editor_with_no_projects_denied(self):
        """Editor with no project scopes is denied projects."""
        editor = _make_user(role=UserRole.editor, scope_project_ids=None)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.project, project_id=uuid4())
        assert exc_info.value.status_code == 403

    def test_editor_project_scope_applies_to_work_packages(self):
        """Project scope also applies to work packages."""
        project_id = uuid4()
        editor = _make_user(role=UserRole.editor, scope_project_ids=[project_id])
        check_write_permission(editor, EntityType.work_package, project_id=project_id)

    # --- User management (admin-only) ---

    def test_editor_cannot_manage_users(self):
        """Editor cannot manage users regardless of scopes."""
        editor = _make_user(
            role=UserRole.editor,
            scope_group_ids=[uuid4()],
            scope_project_ids=[uuid4()],
        )
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.user_management)
        assert exc_info.value.status_code == 403

    # --- Missing scope value (None group_id/project_id) ---

    def test_editor_denied_when_group_id_is_none(self):
        """Editor is denied when entity group_id is None."""
        editor = _make_user(role=UserRole.editor, scope_group_ids=[uuid4()])
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.resource, group_id=None)
        assert exc_info.value.status_code == 403

    def test_editor_denied_when_project_id_is_none(self):
        """Editor is denied when entity project_id is None."""
        editor = _make_user(role=UserRole.editor, scope_project_ids=[uuid4()])
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.project, project_id=None)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Property-based tests — scope checking
# ---------------------------------------------------------------------------


class TestScopeProperties:
    """Property-based tests for scope checking logic."""

    @given(
        entity_type=st.sampled_from(list(EntityType)),
    )
    @settings(max_examples=50, deadline=timedelta(seconds=5))
    def test_admin_always_passes(self, entity_type: EntityType):
        """Admin role always passes check_write_permission regardless of entity type or scope."""
        admin = _make_user(role=UserRole.admin)
        group_id = uuid4()
        project_id = uuid4()
        # Should never raise
        check_write_permission(
            admin,
            entity_type,
            group_id=group_id,
            project_id=project_id,
        )

    @given(
        entity_type=st.sampled_from(list(EntityType)),
    )
    @settings(max_examples=50, deadline=timedelta(seconds=5))
    def test_viewer_always_denied(self, entity_type: EntityType):
        """Viewer role is always denied by check_write_permission."""
        viewer = _make_user(role=UserRole.viewer)
        group_id = uuid4()
        project_id = uuid4()
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(
                viewer,
                entity_type,
                group_id=group_id,
                project_id=project_id,
            )
        assert exc_info.value.status_code == 403

    @given(
        num_groups=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=30, deadline=timedelta(seconds=5))
    def test_editor_in_scope_group_passes(self, num_groups: int):
        """An editor with a group_id in their scope can write resources in that group."""
        group_ids = [uuid4() for _ in range(num_groups)]
        editor = _make_user(role=UserRole.editor, scope_group_ids=group_ids)
        check_write_permission(editor, EntityType.resource, group_id=group_ids[0])

    @given(
        num_groups=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=30, deadline=timedelta(seconds=5))
    def test_editor_out_of_scope_group_denied(self, num_groups: int):
        """An editor writing to a group NOT in their scope is denied."""
        group_ids = [uuid4() for _ in range(num_groups)]
        other_group = uuid4()
        editor = _make_user(role=UserRole.editor, scope_group_ids=group_ids)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.resource, group_id=other_group)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Resource not in your scope"

    @given(
        num_projects=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=20, deadline=timedelta(seconds=5))
    def test_editor_in_scope_project_passes(self, num_projects: int):
        """An editor with a project ID in their scope can write to that project."""
        project_ids = [uuid4() for _ in range(num_projects)]
        editor = _make_user(role=UserRole.editor, scope_project_ids=project_ids)
        check_write_permission(editor, EntityType.project, project_id=project_ids[0])

    @given(
        num_projects=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=20, deadline=timedelta(seconds=5))
    def test_editor_out_of_scope_project_denied(self, num_projects: int):
        """An editor writing to a project NOT in their scope is denied."""
        project_ids = [uuid4() for _ in range(num_projects)]
        other_project = uuid4()
        editor = _make_user(role=UserRole.editor, scope_project_ids=project_ids)
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.project, project_id=other_project)
        assert exc_info.value.status_code == 403

    def test_editor_always_denied_user_management(self):
        """Editor is always denied write access to user_management regardless of scopes."""
        editor = _make_user(
            role=UserRole.editor,
            scope_group_ids=[uuid4()],
            scope_project_ids=[uuid4()],
        )
        with pytest.raises(HTTPException) as exc_info:
            check_write_permission(editor, EntityType.user_management)
        assert exc_info.value.status_code == 403
