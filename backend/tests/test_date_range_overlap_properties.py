"""Property-based tests for date-range overlap and capacity arithmetic.

Tests pure domain logic functions without database access:
- Assignment overlap detection (date ranges)
- Capacity utilization color coding
- Daily assigned percentage computation
"""

from datetime import date, datetime, time, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.assignment import Assignment
from app.models.resource import ResourceType
from app.services.capacity_service import CapacityService, get_utilization_color

# --- Strategies ---

reasonable_dates = st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))


@st.composite
def date_range(draw):
    """Generate a valid date range (start <= end)."""
    start = draw(reasonable_dates)
    delta = draw(st.integers(min_value=0, max_value=365))
    end = start + timedelta(days=delta)
    return start, end


@st.composite
def personal_assignment(draw):
    """Generate a personal assignment with valid date range and allocation."""
    start, end = draw(date_range())
    allocation = draw(st.floats(min_value=1.0, max_value=100.0))
    return Assignment(
        resource_id="00000000-0000-0000-0000-000000000001",
        resource_type=ResourceType.personal,
        work_package_id="00000000-0000-0000-0000-000000000002",
        start_date=start,
        end_date=end,
        allocation_percent=allocation,
    )


@st.composite
def infrastructure_assignment(draw):
    """Generate an infrastructure assignment with valid datetime range."""
    start_date = draw(reasonable_dates)
    start_hour = draw(st.integers(min_value=0, max_value=22))
    duration_hours = draw(st.integers(min_value=1, max_value=23 - start_hour))
    start_at = datetime.combine(start_date, time(start_hour, 0))
    end_at = start_at + timedelta(hours=duration_hours)
    return Assignment(
        resource_id="00000000-0000-0000-0000-000000000001",
        resource_type=ResourceType.infrastructure,
        work_package_id="00000000-0000-0000-0000-000000000002",
        start_at=start_at,
        end_at=end_at,
    )


# --- Property Tests ---


class TestUtilizationColorProperties:
    """Property tests for utilization color coding."""

    @given(utilization=st.floats(min_value=0.0, max_value=79.99))
    @settings(max_examples=100)
    def test_below_80_is_green(self, utilization: float):
        """Utilization below 80% always maps to green."""
        assert get_utilization_color(utilization) == "green"

    @given(utilization=st.floats(min_value=80.0, max_value=100.0))
    @settings(max_examples=100)
    def test_80_to_100_is_yellow(self, utilization: float):
        """Utilization between 80% and 100% always maps to yellow."""
        assert get_utilization_color(utilization) == "yellow"

    @given(utilization=st.floats(min_value=100.01, max_value=500.0))
    @settings(max_examples=100)
    def test_above_100_is_red(self, utilization: float):
        """Utilization above 100% always maps to red."""
        assert get_utilization_color(utilization) == "red"

    @given(utilization=st.floats(min_value=0.0, max_value=500.0))
    @settings(max_examples=200)
    def test_color_is_always_valid(self, utilization: float):
        """Color is always one of green, yellow, red."""
        color = get_utilization_color(utilization)
        assert color in {"green", "yellow", "red"}

    @given(
        u1=st.floats(min_value=0.0, max_value=500.0),
        u2=st.floats(min_value=0.0, max_value=500.0),
    )
    @settings(max_examples=100)
    def test_color_monotonicity(self, u1: float, u2: float):
        """Higher utilization never maps to a 'better' color.

        green < yellow < red in severity ordering.
        """
        severity = {"green": 0, "yellow": 1, "red": 2}
        c1 = get_utilization_color(u1)
        c2 = get_utilization_color(u2)
        if u1 <= u2:
            assert severity[c1] <= severity[c2]


class TestPersonalAssignmentOverlapProperties:
    """Property tests for personal assignment date-range overlap."""

    @given(assignment=personal_assignment(), query_date=reasonable_dates)
    @settings(max_examples=200)
    def test_assignment_contributes_only_within_range(
        self, assignment: Assignment, query_date: date
    ):
        """A personal assignment contributes allocation only on days within its range."""
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            [assignment], ResourceType.personal, query_date
        )
        if assignment.start_date <= query_date <= assignment.end_date:
            assert result == assignment.allocation_percent
        else:
            assert result == 0.0

    @given(
        assignments=st.lists(personal_assignment(), min_size=1, max_size=5),
        query_date=reasonable_dates,
    )
    @settings(max_examples=200)
    def test_total_is_sum_of_overlapping(
        self, assignments: list[Assignment], query_date: date
    ):
        """Total assigned percent is the sum of all overlapping assignments."""
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            assignments, ResourceType.personal, query_date
        )
        expected = sum(
            a.allocation_percent
            for a in assignments
            if a.start_date is not None
            and a.end_date is not None
            and a.allocation_percent is not None
            and a.start_date <= query_date <= a.end_date
        )
        assert abs(result - expected) < 1e-9

    @given(assignment=personal_assignment())
    @settings(max_examples=100)
    def test_no_contribution_before_start(self, assignment: Assignment):
        """No contribution on the day before start_date."""
        day_before = assignment.start_date - timedelta(days=1)
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            [assignment], ResourceType.personal, day_before
        )
        assert result == 0.0

    @given(assignment=personal_assignment())
    @settings(max_examples=100)
    def test_no_contribution_after_end(self, assignment: Assignment):
        """No contribution on the day after end_date."""
        day_after = assignment.end_date + timedelta(days=1)
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            [assignment], ResourceType.personal, day_after
        )
        assert result == 0.0

    @given(assignment=personal_assignment())
    @settings(max_examples=100)
    def test_contribution_on_start_date(self, assignment: Assignment):
        """Assignment contributes on its start_date (inclusive)."""
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            [assignment], ResourceType.personal, assignment.start_date
        )
        assert result == assignment.allocation_percent

    @given(assignment=personal_assignment())
    @settings(max_examples=100)
    def test_contribution_on_end_date(self, assignment: Assignment):
        """Assignment contributes on its end_date (inclusive)."""
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            [assignment], ResourceType.personal, assignment.end_date
        )
        assert result == assignment.allocation_percent


class TestInfrastructureAssignmentOverlapProperties:
    """Property tests for infrastructure assignment time-range overlap."""

    @given(assignment=infrastructure_assignment())
    @settings(max_examples=100)
    def test_infrastructure_is_100_percent_on_overlap_day(self, assignment: Assignment):
        """Infrastructure assignment is 100% on the day it overlaps."""
        day = assignment.start_at.date()
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            [assignment], ResourceType.infrastructure, day
        )
        assert result == 100.0

    @given(assignment=infrastructure_assignment())
    @settings(max_examples=100)
    def test_infrastructure_zero_on_non_overlap_day(self, assignment: Assignment):
        """Infrastructure assignment is 0% on a day it doesn't overlap."""
        # Pick a day well before the assignment
        non_overlap_day = assignment.start_at.date() - timedelta(days=10)
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            [assignment], ResourceType.infrastructure, non_overlap_day
        )
        assert result == 0.0

    @given(query_date=reasonable_dates)
    @settings(max_examples=50)
    def test_empty_assignments_is_zero(self, query_date: date):
        """No assignments means 0% utilization."""
        service = CapacityService.__new__(CapacityService)
        result = service._assigned_percent_for_day(
            [], ResourceType.personal, query_date
        )
        assert result == 0.0
