"""SkillService: Management of skills, skill attributes, and resource skill assignments.

Skills and attributes are global. Assignments are scoped to personal or
infrastructure resources.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import ConflictError, InputValidationError, NotFoundError
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.skill import (
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    Skill,
    SkillAttribute,
)
from app.schemas.skill import (
    ResourceSkillAssignmentResponse,
    ResourceSkillEntry,
    SkillWithAttributesResponse,
)


class SkillService:
    """Service for managing the unified skill system."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    # --- Skills ---

    async def get_all_skills(
        self, limit: int = 100, offset: int = 0
    ) -> tuple[list[Skill], int]:
        """Return all skills sorted alphabetically with pagination.

        Args:
            limit: Maximum number of items to return.
            offset: Number of items to skip.

        Returns:
            Tuple of (list of skills, total count).

        """
        from sqlmodel import func

        total_result = await self.session.execute(
            select(func.count()).select_from(Skill)
        )
        total = total_result.scalar_one()

        statement = select(Skill).order_by(Skill.name.asc()).offset(offset).limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all()), total

    async def get_all_skills_with_attributes(
        self, resource_type: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[SkillWithAttributesResponse], int]:
        """Return skills with their attributes, optionally filtered by type, with pagination.

        Uses a single joined query to load all skills and attributes together,
        avoiding the N+1 pattern of querying attributes per skill.

        Args:
            resource_type: Optional filter by resource type.
            limit: Maximum number of skills to return.
            offset: Number of skills to skip.

        Returns:
            Tuple of (list of skills with attributes, total count).

        """
        from sqlmodel import func

        # Count total matching skills
        count_stmt = select(func.count()).select_from(Skill)
        if resource_type is not None:
            count_stmt = count_stmt.where(Skill.resource_type == resource_type)
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()

        # Load paginated skills
        skill_stmt = select(Skill).order_by(Skill.name.asc())
        if resource_type is not None:
            skill_stmt = skill_stmt.where(Skill.resource_type == resource_type)
        skill_stmt = skill_stmt.offset(offset).limit(limit)
        skill_result = await self.session.execute(skill_stmt)
        skills = list(skill_result.scalars().all())

        if not skills:
            return [], total

        # Load all attributes for the matched skills in one query
        skill_ids = [s.id for s in skills]
        attrs_stmt = (
            select(SkillAttribute)
            .where(SkillAttribute.skill_id.in_(skill_ids))
            .order_by(SkillAttribute.skill_id, SkillAttribute.name.asc())
        )
        attrs_result = await self.session.execute(attrs_stmt)
        all_attributes = list(attrs_result.scalars().all())

        # Group attributes by skill_id
        attrs_by_skill: dict[UUID, list[SkillAttribute]] = {s.id: [] for s in skills}
        for attr in all_attributes:
            attrs_by_skill.setdefault(attr.skill_id, []).append(attr)

        items = [
            SkillWithAttributesResponse(
                id=skill.id,
                name=skill.name,
                resource_type=skill.resource_type,
                attributes=attrs_by_skill.get(skill.id, []),
            )
            for skill in skills
        ]
        return items, total

    async def create_skill(self, name: str, resource_type: str = "personal") -> Skill:
        """Create a new skill after validation."""
        trimmed_name = name.strip()
        self._validate_name(trimmed_name)
        await self._check_skill_name_unique(trimmed_name)

        skill = Skill(name=trimmed_name, resource_type=resource_type)
        self.session.add(skill)
        await self.session.commit()
        return skill

    async def update_skill(self, skill_id: UUID, name: str) -> Skill:
        """Update the name of an existing skill."""
        trimmed_name = name.strip()
        self._validate_name(trimmed_name)

        skill = await self._get_skill_by_id(skill_id)
        await self._check_skill_name_unique(trimmed_name, exclude_id=skill_id)

        skill.name = trimmed_name
        self.session.add(skill)
        await self.session.commit()
        return skill

    async def delete_skill(self, skill_id: UUID) -> None:
        """Delete a skill if no assignments reference any of its attributes."""
        skill = await self._get_skill_by_id(skill_id)
        await self._check_skill_not_in_use(skill_id)

        # Delete all attributes first
        await self.session.execute(
            sa_delete(SkillAttribute).where(SkillAttribute.skill_id == skill_id)
        )
        await self.session.delete(skill)
        await self.session.commit()

    # --- Skill Attributes ---

    async def get_skill_attributes(self, skill_id: UUID) -> list[SkillAttribute]:
        """Return all attributes of a skill sorted alphabetically."""
        await self._get_skill_by_id(skill_id)
        statement = (
            select(SkillAttribute)
            .where(SkillAttribute.skill_id == skill_id)
            .order_by(SkillAttribute.name.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create_skill_attribute(self, skill_id: UUID, name: str) -> SkillAttribute:
        """Create a new attribute for a skill."""
        await self._get_skill_by_id(skill_id)
        trimmed_name = name.strip()
        self._validate_name(trimmed_name)
        await self._check_attribute_name_unique(skill_id, trimmed_name)

        attribute = SkillAttribute(skill_id=skill_id, name=trimmed_name)
        self.session.add(attribute)
        await self.session.commit()
        return attribute

    async def update_skill_attribute(
        self, attribute_id: UUID, name: str
    ) -> SkillAttribute:
        """Update the name of a skill attribute."""
        trimmed_name = name.strip()
        self._validate_name(trimmed_name)

        attribute = await self._get_attribute_by_id(attribute_id)
        await self._check_attribute_name_unique(
            attribute.skill_id, trimmed_name, exclude_id=attribute_id
        )

        attribute.name = trimmed_name
        self.session.add(attribute)
        await self.session.commit()
        return attribute

    async def delete_skill_attribute(self, attribute_id: UUID) -> None:
        """Delete a skill attribute if no assignments reference it."""
        attribute = await self._get_attribute_by_id(attribute_id)
        await self._check_attribute_not_in_use(attribute_id)

        await self.session.delete(attribute)
        await self.session.commit()

    # --- Personal Resource Skills ---

    async def get_personal_resource_skills(
        self, resource_id: UUID
    ) -> list[ResourceSkillAssignmentResponse]:
        """Return all skill assignments for a personal resource."""
        await self._validate_personal_resource_active(resource_id)

        statement = (
            select(PersonalResourceSkill, SkillAttribute, Skill)
            .join(
                SkillAttribute,
                PersonalResourceSkill.skill_attribute_id == SkillAttribute.id,
            )
            .join(Skill, SkillAttribute.skill_id == Skill.id)
            .where(PersonalResourceSkill.resource_id == resource_id)
            .order_by(Skill.name.asc(), SkillAttribute.name.asc())
        )
        result = await self.session.execute(statement)
        rows = result.all()

        return [
            ResourceSkillAssignmentResponse(
                id=assignment.id,
                skill_attribute_id=attribute.id,
                skill_id=skill.id,
                skill_name=skill.name,
                attribute_name=attribute.name,
                valid_from=assignment.valid_from,
                valid_until=assignment.valid_until,
                level=assignment.level,
            )
            for assignment, attribute, skill in rows
        ]

    async def add_personal_resource_skill(
        self,
        resource_id: UUID,
        skill_attribute_id: UUID,
        valid_from: date | None = None,
        valid_until: date | None = None,
        level: int | None = None,
    ) -> ResourceSkillAssignmentResponse:
        """Assign a skill attribute to a personal resource."""
        await self._validate_personal_resource_active(resource_id)
        attribute = await self._get_attribute_by_id(skill_attribute_id)
        skill = await self._get_skill_by_id(attribute.skill_id)
        await self._check_personal_assignment_not_duplicate(
            resource_id, skill_attribute_id
        )

        assignment = PersonalResourceSkill(
            resource_id=resource_id,
            skill_attribute_id=skill_attribute_id,
            valid_from=valid_from,
            valid_until=valid_until,
            level=level,
        )
        self.session.add(assignment)
        await self.session.commit()

        return ResourceSkillAssignmentResponse(
            id=assignment.id,
            skill_attribute_id=attribute.id,
            skill_id=skill.id,
            skill_name=skill.name,
            attribute_name=attribute.name,
        )

    async def remove_personal_resource_skill(
        self, resource_id: UUID, assignment_id: UUID
    ) -> None:
        """Remove a skill assignment from a personal resource."""
        await self._validate_personal_resource_active(resource_id)

        statement = select(PersonalResourceSkill).where(
            PersonalResourceSkill.id == assignment_id,
            PersonalResourceSkill.resource_id == resource_id,
        )
        result = await self.session.execute(statement)
        assignment = result.scalars().first()

        if assignment is None:
            raise NotFoundError("PersonalResourceSkill", assignment_id)

        await self.session.delete(assignment)
        await self.session.commit()

    async def replace_personal_resource_skills(
        self, resource_id: UUID, entries: list[ResourceSkillEntry]
    ) -> list[ResourceSkillAssignmentResponse]:
        """Atomically replace all skill assignments for a personal resource.

        Uses batch queries to load all referenced SkillAttributes and Skills
        in two queries instead of N+1 individual lookups.
        """
        await self._validate_personal_resource_active(resource_id)

        # Ids for the existing validation and batch-loading below. The entries carry
        # the bounds; the id list is what the lookups need.
        skill_attribute_ids = [e.skill_attribute_id for e in entries]

        # Ids for the existing validation and batch-loading below. The entries carry
        # the bounds; the id list is what the lookups need.
        skill_attribute_ids = [e.skill_attribute_id for e in entries]

        # Validate: no duplicates in input
        seen: set[UUID] = set()
        for attr_id in skill_attribute_ids:
            if attr_id in seen:
                raise InputValidationError(f"Duplicate skill_attribute_id: {attr_id}")
            seen.add(attr_id)

        # Batch-load all referenced attributes in one query
        attribute_cache: dict[UUID, SkillAttribute] = {}
        skill_cache: dict[UUID, Skill] = {}

        if skill_attribute_ids:
            attrs_stmt = select(SkillAttribute).where(
                SkillAttribute.id.in_(skill_attribute_ids)
            )
            attrs_result = await self.session.execute(attrs_stmt)
            for attr in attrs_result.scalars().all():
                attribute_cache[attr.id] = attr

        # Check for missing attributes
        invalid_refs: list[str] = []
        for attr_id in skill_attribute_ids:
            if attr_id not in attribute_cache:
                invalid_refs.append(f"SkillAttribute with ID '{attr_id}' not found")

        if invalid_refs:
            raise InputValidationError(f"Invalid entries: {'; '.join(invalid_refs)}")

        # Batch-load all referenced skills in one query
        skill_ids = list({attr.skill_id for attr in attribute_cache.values()})
        if skill_ids:
            skills_stmt = select(Skill).where(Skill.id.in_(skill_ids))
            skills_result = await self.session.execute(skills_stmt)
            for skill in skills_result.scalars().all():
                skill_cache[skill.id] = skill

        # Delete all existing assignments
        await self.session.execute(
            sa_delete(PersonalResourceSkill).where(
                PersonalResourceSkill.resource_id == resource_id
            )
        )

        # Insert new assignments
        new_assignments: list[PersonalResourceSkill] = []
        for entry in entries:
            assignment = PersonalResourceSkill(
                resource_id=resource_id,
                skill_attribute_id=entry.skill_attribute_id,
                valid_from=entry.valid_from,
                valid_until=entry.valid_until,
                level=entry.level,
            )
            self.session.add(assignment)
            new_assignments.append(assignment)

        await self.session.flush()
        await self.session.commit()

        # Build response
        response = [
            ResourceSkillAssignmentResponse(
                id=a.id,
                skill_attribute_id=a.skill_attribute_id,
                valid_from=a.valid_from,
                valid_until=a.valid_until,
                level=a.level,
                skill_id=attribute_cache[a.skill_attribute_id].skill_id,
                skill_name=skill_cache[
                    attribute_cache[a.skill_attribute_id].skill_id
                ].name,
                attribute_name=attribute_cache[a.skill_attribute_id].name,
            )
            for a in new_assignments
        ]
        response.sort(key=lambda r: (r.skill_name.lower(), r.attribute_name.lower()))
        return response

    # --- Infrastructure Resource Skills ---

    async def get_infrastructure_resource_skills(
        self, resource_id: UUID
    ) -> list[ResourceSkillAssignmentResponse]:
        """Return all skill assignments for an infrastructure resource."""
        await self._validate_infrastructure_resource_active(resource_id)

        statement = (
            select(InfrastructureResourceSkill, SkillAttribute, Skill)
            .join(
                SkillAttribute,
                InfrastructureResourceSkill.skill_attribute_id == SkillAttribute.id,
            )
            .join(Skill, SkillAttribute.skill_id == Skill.id)
            .where(InfrastructureResourceSkill.resource_id == resource_id)
            .order_by(Skill.name.asc(), SkillAttribute.name.asc())
        )
        result = await self.session.execute(statement)
        rows = result.all()

        return [
            ResourceSkillAssignmentResponse(
                id=assignment.id,
                skill_attribute_id=attribute.id,
                skill_id=skill.id,
                skill_name=skill.name,
                attribute_name=attribute.name,
                valid_from=assignment.valid_from,
                valid_until=assignment.valid_until,
                level=assignment.level,
            )
            for assignment, attribute, skill in rows
        ]

    async def add_infrastructure_resource_skill(
        self,
        resource_id: UUID,
        skill_attribute_id: UUID,
        valid_from: date | None = None,
        valid_until: date | None = None,
        level: int | None = None,
    ) -> ResourceSkillAssignmentResponse:
        """Assign a skill attribute to an infrastructure resource."""
        await self._validate_infrastructure_resource_active(resource_id)
        attribute = await self._get_attribute_by_id(skill_attribute_id)
        skill = await self._get_skill_by_id(attribute.skill_id)
        await self._check_infrastructure_assignment_not_duplicate(
            resource_id, skill_attribute_id
        )

        assignment = InfrastructureResourceSkill(
            resource_id=resource_id,
            skill_attribute_id=skill_attribute_id,
            valid_from=valid_from,
            valid_until=valid_until,
            level=level,
        )
        self.session.add(assignment)
        await self.session.commit()

        return ResourceSkillAssignmentResponse(
            id=assignment.id,
            skill_attribute_id=attribute.id,
            skill_id=skill.id,
            skill_name=skill.name,
            attribute_name=attribute.name,
        )

    async def remove_infrastructure_resource_skill(
        self, resource_id: UUID, assignment_id: UUID
    ) -> None:
        """Remove a skill assignment from an infrastructure resource."""
        await self._validate_infrastructure_resource_active(resource_id)

        statement = select(InfrastructureResourceSkill).where(
            InfrastructureResourceSkill.id == assignment_id,
            InfrastructureResourceSkill.resource_id == resource_id,
        )
        result = await self.session.execute(statement)
        assignment = result.scalars().first()

        if assignment is None:
            raise NotFoundError("InfrastructureResourceSkill", assignment_id)

        await self.session.delete(assignment)
        await self.session.commit()

    async def replace_infrastructure_resource_skills(
        self, resource_id: UUID, entries: list[ResourceSkillEntry]
    ) -> list[ResourceSkillAssignmentResponse]:
        """Atomically replace all skill assignments for an infrastructure resource.

        Uses batch queries to load all referenced SkillAttributes and Skills
        in two queries instead of N+1 individual lookups.
        """
        await self._validate_infrastructure_resource_active(resource_id)

        # Ids for the validation and batch-loading below; the entries carry the bounds.
        skill_attribute_ids = [e.skill_attribute_id for e in entries]

        # Validate: no duplicates
        seen: set[UUID] = set()
        for attr_id in skill_attribute_ids:
            if attr_id in seen:
                raise InputValidationError(f"Duplicate skill_attribute_id: {attr_id}")
            seen.add(attr_id)

        # Batch-load all referenced attributes in one query
        attribute_cache: dict[UUID, SkillAttribute] = {}
        skill_cache: dict[UUID, Skill] = {}

        if skill_attribute_ids:
            attrs_stmt = select(SkillAttribute).where(
                SkillAttribute.id.in_(skill_attribute_ids)
            )
            attrs_result = await self.session.execute(attrs_stmt)
            for attr in attrs_result.scalars().all():
                attribute_cache[attr.id] = attr

        # Check for missing attributes
        invalid_refs: list[str] = []
        for attr_id in skill_attribute_ids:
            if attr_id not in attribute_cache:
                invalid_refs.append(f"SkillAttribute with ID '{attr_id}' not found")

        if invalid_refs:
            raise InputValidationError(f"Invalid entries: {'; '.join(invalid_refs)}")

        # Batch-load all referenced skills in one query
        skill_ids = list({attr.skill_id for attr in attribute_cache.values()})
        if skill_ids:
            skills_stmt = select(Skill).where(Skill.id.in_(skill_ids))
            skills_result = await self.session.execute(skills_stmt)
            for skill in skills_result.scalars().all():
                skill_cache[skill.id] = skill

        # Delete all existing
        await self.session.execute(
            sa_delete(InfrastructureResourceSkill).where(
                InfrastructureResourceSkill.resource_id == resource_id
            )
        )

        # Insert new
        new_assignments: list[InfrastructureResourceSkill] = []
        for entry in entries:
            assignment = InfrastructureResourceSkill(
                resource_id=resource_id,
                skill_attribute_id=entry.skill_attribute_id,
                valid_from=entry.valid_from,
                valid_until=entry.valid_until,
                level=entry.level,
            )
            self.session.add(assignment)
            new_assignments.append(assignment)

        await self.session.flush()
        await self.session.commit()

        response = [
            ResourceSkillAssignmentResponse(
                id=a.id,
                skill_attribute_id=a.skill_attribute_id,
                valid_from=a.valid_from,
                valid_until=a.valid_until,
                level=a.level,
                skill_id=attribute_cache[a.skill_attribute_id].skill_id,
                skill_name=skill_cache[
                    attribute_cache[a.skill_attribute_id].skill_id
                ].name,
                attribute_name=attribute_cache[a.skill_attribute_id].name,
            )
            for a in new_assignments
        ]
        response.sort(key=lambda r: (r.skill_name.lower(), r.attribute_name.lower()))
        return response

    # --- Search ---

    async def search_personal_by_skills(
        self,
        skill_id: UUID | None = None,
        skill_attribute_id: UUID | None = None,
    ) -> list[dict]:
        """Search active personal resources by skill or skill attribute.

        Loads all skill assignments for matched resources in a single batch
        query to avoid the N+1 pattern of querying per resource.

        Args:
            skill_id: Filter by skill (any attribute of this skill).
            skill_attribute_id: Filter by specific attribute.

        Returns:
            List of matching resources with their skill assignments.

        """
        if skill_id is not None:
            skill = await self.session.get(Skill, skill_id)
            if skill is None:
                raise NotFoundError("Skill", skill_id)

        if skill_attribute_id is not None:
            attribute = await self.session.get(SkillAttribute, skill_attribute_id)
            if attribute is None:
                raise NotFoundError("SkillAttribute", skill_attribute_id)

        # Build query
        if skill_id is not None or skill_attribute_id is not None:
            statement = (
                select(PersonalResource)
                .join(
                    PersonalResourceSkill,
                    PersonalResourceSkill.resource_id == PersonalResource.id,
                )
                .join(
                    SkillAttribute,
                    PersonalResourceSkill.skill_attribute_id == SkillAttribute.id,
                )
                .where(PersonalResource.is_active == True)  # noqa: E712
            )

            if skill_attribute_id is not None:
                statement = statement.where(
                    PersonalResourceSkill.skill_attribute_id == skill_attribute_id
                )
            elif skill_id is not None:
                statement = statement.where(SkillAttribute.skill_id == skill_id)

            statement = statement.distinct()
        else:
            statement = select(PersonalResource).where(
                PersonalResource.is_active == True  # noqa: E712
            )

        statement = statement.order_by(PersonalResource.name.asc()).limit(200)
        result = await self.session.execute(statement)
        resources = list(result.scalars().all())

        if not resources:
            return []

        # Batch-load all skill assignments for matched resources in one query
        resource_ids = [r.id for r in resources]
        skills_stmt = (
            select(PersonalResourceSkill, SkillAttribute, Skill)
            .join(
                SkillAttribute,
                PersonalResourceSkill.skill_attribute_id == SkillAttribute.id,
            )
            .join(Skill, SkillAttribute.skill_id == Skill.id)
            .where(PersonalResourceSkill.resource_id.in_(resource_ids))
            .order_by(Skill.name.asc(), SkillAttribute.name.asc())
        )
        skills_result = await self.session.execute(skills_stmt)
        all_rows = skills_result.all()

        # Group by resource_id
        skills_by_resource: dict[UUID, list[ResourceSkillAssignmentResponse]] = {
            rid: [] for rid in resource_ids
        }
        for assignment, attr, sk in all_rows:
            skills_by_resource[assignment.resource_id].append(
                ResourceSkillAssignmentResponse(
                    id=assignment.id,
                    skill_attribute_id=attr.id,
                    skill_id=sk.id,
                    skill_name=sk.name,
                    attribute_name=attr.name,
                )
            )

        # Build result — resolve group names for the department field
        group_ids = list({r.group_id for r in resources})
        group_names: dict[UUID, str] = {}
        if group_ids:
            from app.models.resource_group import ResourceGroup

            g_stmt = select(ResourceGroup).where(ResourceGroup.id.in_(group_ids))
            g_result = await self.session.execute(g_stmt)
            for g in g_result.scalars().all():
                group_names[g.id] = g.name

        search_results = []
        for resource in resources:
            search_results.append(
                {
                    "id": resource.id,
                    "name": resource.name,
                    "department": group_names.get(resource.group_id, ""),
                    "skills": skills_by_resource.get(resource.id, []),
                }
            )

        return search_results

    # --- Private helpers ---

    def _validate_name(self, trimmed_name: str) -> None:
        """Validate name after trimming."""
        if not trimmed_name:
            raise InputValidationError(
                "The name must not be empty after trimming.", field="name"
            )
        if len(trimmed_name) > 100:
            raise InputValidationError(
                "The name must not exceed 100 characters.", field="name"
            )

    async def _get_skill_by_id(self, skill_id: UUID) -> Skill:
        """Load a skill or raise NotFoundError."""
        skill = await self.session.get(Skill, skill_id)
        if skill is None:
            raise NotFoundError("Skill", skill_id)
        return skill

    async def _get_attribute_by_id(self, attribute_id: UUID) -> SkillAttribute:
        """Load a skill attribute or raise NotFoundError."""
        attribute = await self.session.get(SkillAttribute, attribute_id)
        if attribute is None:
            raise NotFoundError("SkillAttribute", attribute_id)
        return attribute

    async def _check_skill_name_unique(
        self, name: str, exclude_id: UUID | None = None
    ) -> None:
        """Case-insensitive uniqueness check for skill name."""
        statement = select(Skill).where(func.lower(Skill.name) == name.lower())
        if exclude_id is not None:
            statement = statement.where(Skill.id != exclude_id)
        result = await self.session.execute(statement)
        if result.scalars().first() is not None:
            raise ConflictError("A skill with this name already exists.")

    async def _check_attribute_name_unique(
        self, skill_id: UUID, name: str, exclude_id: UUID | None = None
    ) -> None:
        """Case-insensitive uniqueness check for attribute name within a skill."""
        statement = select(SkillAttribute).where(
            SkillAttribute.skill_id == skill_id,
            func.lower(SkillAttribute.name) == name.lower(),
        )
        if exclude_id is not None:
            statement = statement.where(SkillAttribute.id != exclude_id)
        result = await self.session.execute(statement)
        if result.scalars().first() is not None:
            raise ConflictError(
                "An attribute with this name already exists for this skill."
            )

    async def _check_skill_not_in_use(self, skill_id: UUID) -> None:
        """Check that no assignments reference any attribute of this skill."""
        # Get all attribute IDs for this skill
        attr_stmt = select(SkillAttribute.id).where(SkillAttribute.skill_id == skill_id)
        attr_result = await self.session.execute(attr_stmt)
        attr_ids = [row[0] for row in attr_result.all()]

        if not attr_ids:
            return

        # Check personal assignments
        personal_count_stmt = select(func.count()).where(
            PersonalResourceSkill.skill_attribute_id.in_(attr_ids)
        )
        personal_result = await self.session.execute(personal_count_stmt)
        personal_count = personal_result.scalar_one()

        # Check infrastructure assignments
        infra_count_stmt = select(func.count()).where(
            InfrastructureResourceSkill.skill_attribute_id.in_(attr_ids)
        )
        infra_result = await self.session.execute(infra_count_stmt)
        infra_count = infra_result.scalar_one()

        total = personal_count + infra_count
        if total > 0:
            raise ConflictError(
                f"Cannot delete: {total} assignments still reference this skill."
            )

    async def _check_attribute_not_in_use(self, attribute_id: UUID) -> None:
        """Check that no assignments reference this attribute."""
        personal_stmt = select(func.count()).where(
            PersonalResourceSkill.skill_attribute_id == attribute_id
        )
        personal_result = await self.session.execute(personal_stmt)
        personal_count = personal_result.scalar_one()

        infra_stmt = select(func.count()).where(
            InfrastructureResourceSkill.skill_attribute_id == attribute_id
        )
        infra_result = await self.session.execute(infra_stmt)
        infra_count = infra_result.scalar_one()

        total = personal_count + infra_count
        if total > 0:
            raise ConflictError(
                f"Cannot delete: {total} assignments still reference this attribute."
            )

    async def _validate_personal_resource_active(
        self, resource_id: UUID
    ) -> PersonalResource:
        """Check that the personal resource exists and is active."""
        resource = await self.session.get(PersonalResource, resource_id)
        if resource is None or not resource.is_active:
            raise NotFoundError("PersonalResource", resource_id)
        return resource

    async def _validate_infrastructure_resource_active(
        self, resource_id: UUID
    ) -> InfrastructureResource:
        """Check that the infrastructure resource exists and is active."""
        resource = await self.session.get(InfrastructureResource, resource_id)
        if resource is None or not resource.is_active:
            raise NotFoundError("InfrastructureResource", resource_id)
        return resource

    async def _check_personal_assignment_not_duplicate(
        self, resource_id: UUID, skill_attribute_id: UUID
    ) -> None:
        """Check that the assignment does not already exist."""
        statement = select(PersonalResourceSkill).where(
            PersonalResourceSkill.resource_id == resource_id,
            PersonalResourceSkill.skill_attribute_id == skill_attribute_id,
        )
        result = await self.session.execute(statement)
        if result.scalars().first() is not None:
            raise ConflictError("This skill attribute is already assigned.")

    async def _check_infrastructure_assignment_not_duplicate(
        self, resource_id: UUID, skill_attribute_id: UUID
    ) -> None:
        """Check that the assignment does not already exist."""
        statement = select(InfrastructureResourceSkill).where(
            InfrastructureResourceSkill.resource_id == resource_id,
            InfrastructureResourceSkill.skill_attribute_id == skill_attribute_id,
        )
        result = await self.session.execute(statement)
        if result.scalars().first() is not None:
            raise ConflictError("This skill attribute is already assigned.")
