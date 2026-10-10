"""Validate structural group writes before changing the inherited calendar."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.calendar import ResourceWorkProfile
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.services.conflict_refresh import refresh_resources
from app.services.graph_locks import lock_graph
from app.services.partial_update import UNSET, UnsetType


class ResourceGroupService:
    """Keep same-type group trees acyclic, including concurrent PostgreSQL writes."""

    def __init__(self, session: AsyncSession):
        """Use the request's transaction and audit actor."""
        self.session = session

    async def _tree(self) -> dict[UUID, tuple[UUID | None, ResourceType]]:
        rows = await self.session.execute(
            select(
                ResourceGroup.id, ResourceGroup.parent_id, ResourceGroup.resource_type
            )
        )
        return {rid: (parent, kind) for rid, parent, kind in rows}

    async def _validate_parent(
        self, group_id: UUID | None, kind: ResourceType, parent_id: UUID | None
    ) -> None:
        if parent_id is None:
            return
        tree = await self._tree()
        if parent_id not in tree:
            raise NotFoundError("ResourceGroup", parent_id)
        visited: set[UUID] = set()
        current: UUID | None = parent_id
        while current is not None:
            if current == group_id or current in visited:
                raise BusinessRuleError(
                    "A resource group hierarchy cannot contain a cycle.",
                    field="parent_id",
                )
            visited.add(current)
            parent, parent_kind = tree[current]
            if parent_kind != kind:
                raise BusinessRuleError(
                    "Parent and child groups must have the same resource type.",
                    field="parent_id",
                )
            current = parent

    async def create(
        self, name: str, resource_type: ResourceType, parent_id: UUID | None
    ) -> ResourceGroup:
        """Create a group after validating its parent under the graph lock."""
        if parent_id is not None:
            await lock_graph(self.session, "resource_groups")
        await self._validate_parent(None, resource_type, parent_id)
        group = ResourceGroup(
            name=name.strip(), resource_type=resource_type, parent_id=parent_id
        )
        self.session.add(group)
        await self.session.commit()
        return group

    async def delete(self, group_id: UUID) -> None:
        """Delete only an unused leaf; never detach children or calendar bindings."""
        await lock_graph(self.session, "resource_groups")
        group = await self.session.get(
            ResourceGroup, group_id, with_for_update=True, populate_existing=True
        )
        if group is None:
            raise NotFoundError("ResourceGroup", group_id)
        # The row lock also serializes FK inserts. A competing binding/resource
        # writer must retain KEY SHARE on this group until its commit.
        for model, column, dependency in (
            (ResourceGroup, ResourceGroup.parent_id, "subgroups"),
            (PersonalResource, PersonalResource.group_id, "personal resources"),
            (
                InfrastructureResource,
                InfrastructureResource.group_id,
                "infrastructure resources",
            ),
            (
                ResourceWorkProfile,
                ResourceWorkProfile.group_id,
                "work-profile bindings",
            ),
        ):
            count = await self.session.scalar(
                select(func.count()).select_from(model).where(column == group_id)
            )
            if count:
                raise ConflictError(
                    f"Cannot delete: {count} {dependency} still reference this group."
                )
        await self.session.delete(group)
        await self.session.commit()

    async def update(
        self,
        group_id: UUID,
        name: str | None = None,
        parent_id: UUID | None | UnsetType = UNSET,
    ) -> ResourceGroup:
        """Validate first; explicit null detaches while omission preserves the parent."""
        if not isinstance(parent_id, UnsetType):
            await lock_graph(self.session, "resource_groups")
        group = await self.session.get(
            ResourceGroup, group_id, with_for_update=True, populate_existing=True
        )
        if group is None:
            raise NotFoundError("ResourceGroup", group_id)
        affected: list[UUID] = []
        if not isinstance(parent_id, UnsetType):
            await self._validate_parent(group_id, group.resource_type, parent_id)
            if parent_id != group.parent_id:
                affected = await self._descendant_resources(group_id)
        if name is not None:
            group.name = name.strip()
        if not isinstance(parent_id, UnsetType):
            group.parent_id = parent_id
        group.updated_at = datetime.now(UTC)
        await self.session.commit()
        if affected:
            await refresh_resources(self.session, affected)
        return group

    async def _descendant_resources(self, group_id: UUID) -> list[UUID]:
        tree = await self._tree()
        children: dict[UUID | None, list[UUID]] = {}
        for rid, (parent, _kind) in tree.items():
            children.setdefault(parent, []).append(rid)
        descendants: set[UUID] = set()
        pending = [group_id]
        while pending:
            current = pending.pop()
            if current not in descendants:
                descendants.add(current)
                pending.extend(children.get(current, []))
        rows = await self.session.scalars(
            union_all(
                select(PersonalResource.id).where(
                    PersonalResource.group_id.in_(descendants)
                ),
                select(InfrastructureResource.id).where(
                    InfrastructureResource.group_id.in_(descendants)
                ),
            )
        )
        return list(rows)
