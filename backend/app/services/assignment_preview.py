"""Read-only impact calculation for one proposed assignment change."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.assignment import Assignment
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.schemas.assignment import (
    AssignmentPreviewRequest,
    AssignmentPreviewResponse,
    PreviewCapacityDay,
    PreviewConflict,
    PreviewResource,
)
from app.services.assignment_service import (
    AssignmentService,
    _validate_assignment_fields,
)
from app.services.capacity_service import CapacityService
from app.services.conflict_service import ConflictPeriod, ConflictService
from app.services.freeze_enforcement import span_of
from app.services.planning_freeze import Span


def _in_windows(period: ConflictPeriod, windows: list[Span]) -> bool:
    return any(
        window.start is not None
        and window.end is not None
        and period.start_date <= window.end
        and period.end_date >= window.start
        for window in windows
    )


def _serialize_conflicts(
    periods: list[ConflictPeriod], windows: list[Span]
) -> list[PreviewConflict]:
    return [
        PreviewConflict(
            cause=period.cause,
            start_date=period.start_date,
            end_date=period.end_date,
            total_assigned_percent=period.total_assigned_percent,
            available_percent=period.available_percent,
        )
        for period in periods
        if _in_windows(period, windows)
    ]


class AssignmentPreviewService:
    """Compare persisted and hypothetical schedules without mutating ORM rows."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def preview(
        self, data: AssignmentPreviewRequest
    ) -> AssignmentPreviewResponse:
        """Return before/after impacts using only database reads."""
        _validate_assignment_fields(
            data.resource_id,
            data.resource_type,
            data.work_package_id,
            data.start_date,
            data.end_date,
            data.allocation_percent,
            data.start_at,
            data.end_at,
        )
        assignment_service = AssignmentService(self.session)
        await assignment_service._check_resource_exists(
            data.resource_id, data.resource_type
        )
        await assignment_service._check_work_package_exists(data.work_package_id)

        existing = (
            await assignment_service.get_by_id(data.assignment_id)
            if data.assignment_id is not None
            else None
        )
        proposed = Assignment(
            resource_id=data.resource_id,
            resource_type=data.resource_type,
            work_package_id=data.work_package_id,
            start_date=data.start_date,
            end_date=data.end_date,
            allocation_percent=data.allocation_percent,
            start_at=data.start_at,
            end_at=data.end_at,
        )
        if existing is not None:
            proposed.id = existing.id

        # Preview must fail on a duplicate just as creation does.
        duplicate_result = await self.session.execute(
            select(Assignment).where(
                Assignment.resource_id == data.resource_id,
                Assignment.work_package_id == data.work_package_id,
            )
        )
        if any(
            row.id != data.assignment_id for row in duplicate_result.scalars().all()
        ):
            raise ConflictError(
                "This resource is already assigned to this work package."
            )

        windows_by_resource: dict[UUID, list[Span]] = {
            data.resource_id: [span_of(proposed)]
        }
        if existing:
            windows_by_resource.setdefault(existing.resource_id, []).append(
                span_of(existing)
            )
        for windows in windows_by_resource.values():
            for window in windows:
                if window.start is None or window.end is None:
                    raise BusinessRuleError("A complete assignment period is required.")
                if (window.end - window.start).days > 365:
                    raise BusinessRuleError(
                        "Preview is limited to assignment periods of 366 days."
                    )

        conflict_service = ConflictService(self.session)
        capacity_service = CapacityService(self.session)
        resources: list[PreviewResource] = []
        for resource_id, windows in windows_by_resource.items():
            resource_type = data.resource_type
            if resource_id != data.resource_id and existing is not None:
                resource_type = existing.resource_type
            if resource_type == ResourceType.personal:
                resource = await self.session.get(PersonalResource, resource_id)
            else:
                resource = await self.session.get(InfrastructureResource, resource_id)
            if resource is None:
                raise NotFoundError(resource_type.value, resource_id)

            result = await self.session.execute(
                select(Assignment).where(Assignment.resource_id == resource_id)
            )
            before = list(result.scalars().all())
            after = [row for row in before if existing is None or row.id != existing.id]
            if resource_id == proposed.resource_id:
                after.append(proposed)

            before_conflicts = await conflict_service.calculate_periods(
                resource_id, before
            )
            after_conflicts = await conflict_service.calculate_periods(
                resource_id, after
            )
            capacity_days: list[PreviewCapacityDay] = []
            if resource_type == ResourceType.personal:
                days: dict[date, PreviewCapacityDay] = {}
                for window in windows:
                    # The two windows may be far apart: calculate each independently.
                    before_days = (
                        await capacity_service.calculate_utilization_for_assignments(
                            resource_id, window.start, window.end, before
                        )
                    )
                    after_days = (
                        await capacity_service.calculate_utilization_for_assignments(
                            resource_id, window.start, window.end, after
                        )
                    )
                    for old, new in zip(before_days, after_days, strict=True):
                        if old.assigned_minutes != new.assigned_minutes:
                            days[old.date] = PreviewCapacityDay(
                                date=old.date,
                                available_percent=old.available,
                                assigned_before_percent=old.assigned,
                                assigned_after_percent=new.assigned,
                            )
                capacity_days = [days[day] for day in sorted(days)]

            resources.append(
                PreviewResource(
                    resource_id=resource_id,
                    resource_name=resource.name,
                    resource_type=resource_type,
                    conflicts_before=_serialize_conflicts(before_conflicts, windows),
                    conflicts_after=_serialize_conflicts(after_conflicts, windows),
                    capacity_days=capacity_days,
                )
            )
        return AssignmentPreviewResponse(resources=resources)
