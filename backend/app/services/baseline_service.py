"""BaselineService: freeze the plan and compare the live plan against it.

The diff is the deliverable, not the snapshot (ADR-007). It is a module-level pure
function over dictionaries so it can be tested without a database, matching how the
rest of this project tests services.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.assignment import Assignment
from app.models.baseline import BASELINE_ENTITY_TYPES, Baseline, BaselineEntry
from app.models.project import Project, WorkPackage

# Bookkeeping columns are excluded from the payload: they change on every write and
# would report a row as drifted when nothing about the plan moved.
IGNORED_FIELDS = frozenset({"created_at", "updated_at"})


@dataclass
class EntityDiff:
    """How one entity differs between a baseline and the live plan."""

    entity_type: str
    entity_id: UUID
    changes: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class BaselineDiff:
    """The drift of the live plan against one baseline.

    ``added`` and ``removed`` are not error states. An assignment created after the
    freeze is genuinely new work, and one deleted is work that went away — both are
    the answer rather than a problem with the comparison.
    """

    added: list[EntityDiff] = field(default_factory=list)
    removed: list[EntityDiff] = field(default_factory=list)
    changed: list[EntityDiff] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        """Whether the live plan differs from the baseline at all."""
        return bool(self.added or self.removed or self.changed)


def _jsonable(value: Any) -> Any:
    """Reduce a column value to something JSON can carry and compare."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def snapshot_payload(obj: Any) -> dict[str, Any]:
    """The field values of one entity, reduced for storage and comparison."""
    payload: dict[str, Any] = {}
    for name in type(obj).model_fields:
        if name in IGNORED_FIELDS:
            continue
        payload[name] = _jsonable(getattr(obj, name, None))
    return payload


def diff_payloads(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Field-by-field differences between two snapshots of one entity.

    Only keys present in BOTH are compared. A field added to the model since the
    baseline was taken therefore reports as new rather than as a change from None,
    and a field removed silently stops being compared — the old value is not wrong,
    it is no longer meaningful.
    """
    changes: dict[str, dict[str, Any]] = {}
    for key in baseline.keys() & current.keys():
        if baseline[key] != current[key]:
            changes[key] = {"baseline": baseline[key], "current": current[key]}
    return changes


def diff_snapshots(
    baseline: dict[tuple[str, UUID], dict[str, Any]],
    current: dict[tuple[str, UUID], dict[str, Any]],
) -> BaselineDiff:
    """Compare a frozen plan against the live one.

    Args:
        baseline: ``{(entity_type, entity_id): payload}`` as frozen.
        current: the same shape, read from the live plan.

    Returns:
        Added, removed and changed entities. An entity present in both with an
        identical payload appears nowhere, so an unchanged plan yields an empty
        diff rather than a list of everything.
    """
    result = BaselineDiff()

    for key in current.keys() - baseline.keys():
        entity_type, entity_id = key
        result.added.append(EntityDiff(entity_type=entity_type, entity_id=entity_id))

    for key in baseline.keys() - current.keys():
        entity_type, entity_id = key
        result.removed.append(EntityDiff(entity_type=entity_type, entity_id=entity_id))

    for key in baseline.keys() & current.keys():
        changes = diff_payloads(baseline[key], current[key])
        if changes:
            entity_type, entity_id = key
            result.changed.append(
                EntityDiff(
                    entity_type=entity_type, entity_id=entity_id, changes=changes
                )
            )

    result.added.sort(key=lambda d: (d.entity_type, str(d.entity_id)))
    result.removed.sort(key=lambda d: (d.entity_type, str(d.entity_id)))
    result.changed.sort(key=lambda d: (d.entity_type, str(d.entity_id)))
    return result


class BaselineService:
    """Freeze plans and compare against them."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def _live_snapshot(self) -> dict[tuple[str, UUID], dict[str, Any]]:
        """Read the current plan in the shape a baseline stores it."""
        snapshot: dict[tuple[str, UUID], dict[str, Any]] = {}
        # Each query is issued separately rather than looping over a list of model classes.
        # The loop reads obj.id, and a list of classes types that as the SQLModel base — which
        # has no id, so the attribute access goes unchecked and a renamed primary key would
        # reach runtime. Three lines of repetition buys the check back.
        for entity_type, rows in (
            ("projects", (await self.session.execute(select(Project))).scalars().all()),
            (
                "work_packages",
                (await self.session.execute(select(WorkPackage))).scalars().all(),
            ),
            (
                "assignments",
                (await self.session.execute(select(Assignment))).scalars().all(),
            ),
        ):
            for obj in rows:
                snapshot[(entity_type, obj.id)] = snapshot_payload(obj)
        return snapshot

    async def list_baselines(self) -> list[Baseline]:
        """All baselines, newest first."""
        result = await self.session.execute(
            select(Baseline).order_by(Baseline.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_baseline(self, baseline_id: UUID) -> Baseline:
        """One baseline, or 404."""
        baseline = await self.session.get(Baseline, baseline_id)
        if baseline is None:
            raise NotFoundError("Baseline", baseline_id)
        return baseline

    async def create_baseline(
        self,
        name: str,
        note: str | None = None,
        created_by: UUID | None = None,
        make_current: bool = True,
    ) -> tuple[Baseline, int]:
        """Freeze the current plan. Returns the baseline and its entry count."""
        if make_current:
            await self._clear_current()

        baseline = Baseline(
            name=name, note=note, created_by=created_by, is_current=make_current
        )
        self.session.add(baseline)
        await self.session.flush()

        live = await self._live_snapshot()
        for (entity_type, entity_id), payload in live.items():
            self.session.add(
                BaselineEntry(
                    baseline_id=baseline.id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    payload=payload,
                )
            )

        await self.session.commit()
        await self.session.refresh(baseline)
        return baseline, len(live)

    async def _clear_current(self) -> None:
        """Unset the current marker, ORM-mutated so the change is audited."""
        result = await self.session.execute(
            select(Baseline).where(Baseline.is_current == True)  # noqa: E712
        )
        for existing in result.scalars().all():
            existing.is_current = False
            self.session.add(existing)

    async def current_baseline(self) -> Baseline | None:
        """The baseline drift is shown against by default."""
        result = await self.session.execute(
            select(Baseline).where(Baseline.is_current == True)  # noqa: E712
        )
        return result.scalars().first()

    async def diff(self, baseline_id: UUID) -> BaselineDiff:
        """Drift of the live plan against one baseline."""
        await self.get_baseline(baseline_id)

        result = await self.session.execute(
            select(BaselineEntry).where(BaselineEntry.baseline_id == baseline_id)
        )
        frozen = {
            (entry.entity_type, entry.entity_id): entry.payload
            for entry in result.scalars().all()
        }
        return diff_snapshots(frozen, await self._live_snapshot())

    async def delete_baseline(self, baseline_id: UUID) -> None:
        """Delete a baseline and its entries.

        A header without its rows is not a partial baseline, it is a lie, so the
        entries go with it.
        """
        baseline = await self.get_baseline(baseline_id)
        if baseline.is_current:
            raise BusinessRuleError(
                "the current baseline cannot be deleted; mark another one current first"
            )
        result = await self.session.execute(
            select(BaselineEntry).where(BaselineEntry.baseline_id == baseline_id)
        )
        for entry in result.scalars().all():
            await self.session.delete(entry)
        await self.session.delete(baseline)
        await self.session.commit()


__all__ = [
    "BASELINE_ENTITY_TYPES",
    "BaselineDiff",
    "BaselineService",
    "EntityDiff",
    "diff_payloads",
    "diff_snapshots",
    "snapshot_payload",
]
