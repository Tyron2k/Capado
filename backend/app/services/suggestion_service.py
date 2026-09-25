"""SuggestionService: Calculation and ranking of suitable resources for a work package.

Qualifications are read from the unified skill system (``personal_resource_skills``).
Optional filtering by skill / attribute runs in the frontend via the dedicated
``/api/personal-resources/search`` endpoint and intersects the results with the
suggestions from this service.

Performance: Assignments and absences for all candidate resources are loaded in
two bulk queries upfront, then capacity is computed in-memory per resource/day
without additional DB round-trips.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.absence import Absence
from app.models.assignment import Assignment
from app.models.resource import PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.skill import PersonalResourceSkill, Skill, SkillAttribute
from app.services.capacity_service import BASE_CAPACITY_PERCENT


@dataclass
class ResourceSuggestion:
    """A single resource suggestion with scoring."""

    resource_id: UUID
    resource_name: str
    qualification_summary: str
    department: str
    availability_status: str  # "available" | "partially_available" | "unavailable"
    average_free_capacity: float  # Average free percent/day
    reason: str  # Explanation of suitability


class SuggestionService:
    """Calculates resource suggestions for a work package.

    Uses bulk-loaded assignments and absences to compute daily free capacity
    in-memory, eliminating per-resource per-day DB queries.
    """

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def get_suggestions(
        self,
        start_date: date,
        end_date: date,
        allocation_percent: float,
        work_package_id: UUID | None = None,
    ) -> list[ResourceSuggestion]:
        """Compute resource suggestions ranked by availability.

        Algorithm:
        1. Load all active personal resources.
        2. Load qualification summaries from the skill system in one query.
        3. Bulk-load all assignments and absences overlapping the date range.
        4. Compute free capacity per resource per day in-memory.
        5. Classify and sort; filter out unavailable resources.

        Args:
            start_date: Start of the planning window.
            end_date: End of the planning window.
            allocation_percent: Required daily allocation percentage.
            work_package_id: Exclude resources already assigned to this work package.

        Returns:
            Sorted list of available/partially-available resources.

        """
        # 1. Load all active personal resources
        resources = await self._load_active_personal_resources()
        if not resources:
            return []

        if work_package_id is not None:
            assigned_stmt = select(Assignment.resource_id).where(
                Assignment.work_package_id == work_package_id
            )
            assigned_result = await self.session.execute(assigned_stmt)
            assigned_ids = set(assigned_result.scalars().all())
            resources = [
                resource for resource in resources if resource.id not in assigned_ids
            ]
            if not resources:
                return []

        resource_ids = [r.id for r in resources]

        # 2. Load qualification summaries in one query
        summaries = await self._load_qualification_summaries(resource_ids)

        # 2b. Load group names
        group_ids = list({r.group_id for r in resources})
        group_names: dict[UUID, str] = {}
        if group_ids:
            g_stmt = select(ResourceGroup).where(ResourceGroup.id.in_(group_ids))
            g_result = await self.session.execute(g_stmt)
            for g in g_result.scalars().all():
                group_names[g.id] = g.name

        # 3. Bulk-load assignments and absences overlapping [start_date, end_date]
        assignments_by_resource = await self._bulk_load_assignments(
            resource_ids, start_date, end_date
        )
        absences_by_resource = await self._bulk_load_absences(
            resource_ids, start_date, end_date
        )

        # 4 + 5. Compute capacity per resource and classify
        suggestions: list[ResourceSuggestion] = []
        for resource in resources:
            daily_free = self._compute_daily_free_capacity(
                resource.id,
                start_date,
                end_date,
                assignments_by_resource.get(resource.id, []),
                absences_by_resource.get(resource.id, []),
            )

            status = self._classify_availability(daily_free, allocation_percent)
            avg_free_capacity = self._calculate_average(daily_free)
            summary = summaries.get(resource.id, "")
            reason = self._build_reason(resource, status, avg_free_capacity, summary)

            suggestions.append(
                ResourceSuggestion(
                    resource_id=resource.id,
                    resource_name=resource.name,
                    qualification_summary=summary,
                    department=group_names.get(resource.group_id, ""),
                    availability_status=status,
                    average_free_capacity=round(avg_free_capacity, 2),
                    reason=reason,
                )
            )

        suggestions = self._sort_suggestions(suggestions)
        suggestions = [s for s in suggestions if s.availability_status != "unavailable"]
        return suggestions

    # --- Data Loading ---

    async def _load_active_personal_resources(self) -> list[PersonalResource]:
        """Load all active personal resources from the database."""
        statement = select(PersonalResource).where(PersonalResource.is_active.is_(True))
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def _load_qualification_summaries(
        self, resource_ids: list[UUID]
    ) -> dict[UUID, str]:
        """Generate a string summary of skills per resource_id.

        Format: ``"Skill1/Attr1, Skill1/Attr2, Skill2/Attr3"`` sorted alphabetically.
        Empty string when no assignments exist.
        """
        if not resource_ids:
            return {}

        stmt = (
            select(
                PersonalResourceSkill.resource_id,
                Skill.name.label("skill_name"),
                SkillAttribute.name.label("attribute_name"),
            )
            .join(
                SkillAttribute,
                PersonalResourceSkill.skill_attribute_id == SkillAttribute.id,
            )
            .join(Skill, SkillAttribute.skill_id == Skill.id)
            .where(PersonalResourceSkill.resource_id.in_(resource_ids))
            .order_by(Skill.name.asc(), SkillAttribute.name.asc())
        )
        result = await self.session.execute(stmt)

        pairs_by_resource: dict[UUID, list[str]] = {rid: [] for rid in resource_ids}
        for row in result.all():
            pairs_by_resource.setdefault(row.resource_id, []).append(
                f"{row.skill_name}/{row.attribute_name}"
            )

        return {rid: ", ".join(pairs) for rid, pairs in pairs_by_resource.items()}

    async def _bulk_load_assignments(
        self,
        resource_ids: list[UUID],
        start_date: date,
        end_date: date,
    ) -> dict[UUID, list[Assignment]]:
        """Load all personal assignments overlapping the date range in one query.

        Args:
            resource_ids: Resources to load assignments for.
            start_date: Range start.
            end_date: Range end.

        Returns:
            Mapping of resource_id → list of overlapping assignments.

        """
        stmt = select(Assignment).where(
            Assignment.resource_id.in_(resource_ids),
            Assignment.resource_type == ResourceType.personal,
            Assignment.start_date <= end_date,
            Assignment.end_date >= start_date,
        )
        result = await self.session.execute(stmt)
        by_resource: dict[UUID, list[Assignment]] = {}
        for a in result.scalars().all():
            by_resource.setdefault(a.resource_id, []).append(a)
        return by_resource

    async def _bulk_load_absences(
        self,
        resource_ids: list[UUID],
        start_date: date,
        end_date: date,
    ) -> dict[UUID, list[Absence]]:
        """Load all absences overlapping the date range in one query.

        Args:
            resource_ids: Resources to load absences for.
            start_date: Range start.
            end_date: Range end.

        Returns:
            Mapping of resource_id → list of overlapping absences.

        """
        stmt = select(Absence).where(
            Absence.resource_id.in_(resource_ids),
            Absence.start_date <= end_date,
            Absence.end_date >= start_date,
        )
        result = await self.session.execute(stmt)
        by_resource: dict[UUID, list[Absence]] = {}
        for ab in result.scalars().all():
            by_resource.setdefault(ab.resource_id, []).append(ab)
        return by_resource

    # --- In-Memory Capacity Computation ---

    def _compute_daily_free_capacity(
        self,
        resource_id: UUID,
        start_date: date,
        end_date: date,
        assignments: list[Assignment],
        absences: list[Absence],
    ) -> list[float]:
        """Compute free capacity per day purely in-memory (no DB calls).

        For each day in the range: free = BASE_CAPACITY - assigned - absent.

        Args:
            resource_id: The resource (for documentation; not used for queries).
            start_date: Range start.
            end_date: Range end.
            assignments: Pre-loaded assignments overlapping this range.
            absences: Pre-loaded absences overlapping this range.

        Returns:
            List of free-capacity percentages, one per day.

        """
        capacities: list[float] = []
        current = start_date

        while current <= end_date:
            assigned = 0.0
            for a in assignments:
                if (
                    a.start_date is not None
                    and a.end_date is not None
                    and a.start_date <= current <= a.end_date
                    and a.allocation_percent is not None
                ):
                    assigned += a.allocation_percent

            absent = 0.0
            for ab in absences:
                if ab.start_date <= current <= ab.end_date:
                    absent += ab.allocation_percent

            free = max(0.0, BASE_CAPACITY_PERCENT - assigned - absent)
            capacities.append(free)
            current += timedelta(days=1)

        return capacities

    # --- Classification & Sorting ---

    def _classify_availability(
        self,
        daily_free_capacities: list[float],
        allocation_percent: float,
    ) -> str:
        """Classify the availability status based on daily free capacity.

        Args:
            daily_free_capacities: Free capacity per day.
            allocation_percent: Required daily allocation.

        Returns:
            One of "available", "partially_available", "unavailable".

        """
        if not daily_free_capacities:
            return "unavailable"

        total_days = len(daily_free_capacities)
        sufficient_days = sum(
            1 for c in daily_free_capacities if c >= allocation_percent
        )
        zero_days = sum(1 for c in daily_free_capacities if c == 0.0)

        if sufficient_days == total_days:
            return "available"
        elif zero_days == total_days:
            return "unavailable"
        else:
            return "partially_available"

    def _calculate_average(self, daily_free_capacities: list[float]) -> float:
        """Average free capacity per day."""
        if not daily_free_capacities:
            return 0.0
        return sum(daily_free_capacities) / len(daily_free_capacities)

    def _sort_suggestions(
        self, suggestions: list[ResourceSuggestion]
    ) -> list[ResourceSuggestion]:
        """Sort suggestions: available > partial > unavailable, within by capacity desc."""
        status_order = {
            "available": 0,
            "partially_available": 1,
            "unavailable": 2,
        }
        return sorted(
            suggestions,
            key=lambda s: (
                status_order.get(s.availability_status, 99),
                -s.average_free_capacity,
            ),
        )

    def _build_reason(
        self,
        resource: PersonalResource,
        status: str,
        avg_free_capacity: float,
        qualification_summary: str,
    ) -> str:
        """Build an explanation of suitability.

        Args:
            resource: The personal resource.
            status: Availability classification.
            avg_free_capacity: Average free capacity percentage.
            qualification_summary: Skill summary string.

        Returns:
            Human-readable explanation string.

        """
        parts: list[str] = []

        if qualification_summary:
            parts.append(f"Qualifications: {qualification_summary}")
        else:
            parts.append("No skills assigned")

        status_labels = {
            "available": "full availability in the time range",
            "partially_available": "limited availability in the time range",
            "unavailable": "no availability in the time range",
        }
        parts.append(status_labels.get(status, ""))
        parts.append(f"avg. {avg_free_capacity:.1f}%/day free")

        return ", ".join(p for p in parts if p)
