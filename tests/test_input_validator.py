import pytest

from datetime import datetime, timezone, time, date
from optimizer.models import Employee, DateTimeShift, SchedulingPolicy, WeeklyAvailability, AvailabilityException, FixedAssignment, ShiftRequirement
from optimizer.input_validator import validate_scheduling_inputs


def make_shift(shift_id, day, start_hour, end_hour, required_staff, required_skill):
    """Create a timezone-aware shift anchored to 23 November 2026."""
    from datetime import timedelta

    base = datetime(2026, 11, 23, tzinfo=timezone.utc)
    return DateTimeShift(
        id=shift_id,
        starts_at=base + timedelta(days=day, hours=start_hour),
        ends_at=base + timedelta(days=day, hours=end_hour),
        requirements=(ShiftRequirement(required_skill, required_staff),),
    )


def test_duplicate_employee_ids():
    employees = [
        Employee(1, "Alice", frozenset({"server"}), 16),
        Employee(1, "Bob", frozenset({"cashier"}), 16),
    ]

    shifts = []

    with pytest.raises(ValueError, match="Duplicate employee IDs"):
        validate_scheduling_inputs(employees, shifts)


def test_duplicate_shift_ids():
    employees = [
        Employee(1, "Alice", frozenset({"server"}), 16),
    ]

    shifts = [
        make_shift(1, 0, 9, 13, 1, "server"),
        make_shift(1, 1, 9, 13, 1, "server"),
    ]

    with pytest.raises(ValueError, match="Duplicate shift IDs"):
        validate_scheduling_inputs(employees, shifts)


def test_empty_employee_dataset():
    with pytest.raises(ValueError, match="At least one employee"):
        validate_scheduling_inputs([], [])


def test_valid_scheduling_inputs():
    employees = [
        Employee(
            id=353458,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
        ),
        Employee(
            id=782941,
            name="Bob",
            skills=frozenset({"cashier"}),
            max_hours=20,
        ),
    ]

    shifts = [
        make_shift(1001, 0, 9, 13, 1, "server"),
    ]

    # Valid data should not raise an exception.
    validate_scheduling_inputs(employees, shifts)


def test_empty_shift_dataset():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
        )
    ]

    # No shifts have been created yet.
    validate_scheduling_inputs(employees, [])


def test_default_scheduling_policy():
    policy = SchedulingPolicy()

    assert policy.minimum_rest_hours == 0
    assert policy.enforce_minimum_rest is False
    assert policy.fairness_enabled is True


def test_custom_scheduling_policy():
    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
        fairness_enabled=False,
    )

    assert policy.minimum_rest_hours == 11
    assert policy.enforce_minimum_rest is True
    assert policy.fairness_enabled is False


@pytest.mark.parametrize(
    "invalid_hours",
    [-1, -5, 2.5, "eleven", None, True, False],
)
def test_invalid_minimum_rest_hours(invalid_hours):
    with pytest.raises(ValueError):
        SchedulingPolicy(minimum_rest_hours=invalid_hours)


@pytest.mark.parametrize(
    "invalid_value",
    ["yes", 1, 0, None, 3.5],
)
def test_invalid_enforce_minimum_rest(invalid_value):
    with pytest.raises(ValueError):
        SchedulingPolicy(
            enforce_minimum_rest=invalid_value
        )


@pytest.mark.parametrize(
    "invalid_value",
    ["yes", 1, 0, None, 3.5],
)
def test_invalid_fairness_enabled(invalid_value):
    with pytest.raises(ValueError):
        SchedulingPolicy(
            fairness_enabled=invalid_value
        )


def test_employee_supports_datetime_availability():
    start = datetime(
        2026, 11, 21, 18, 0,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2026, 11, 22, 3, 0,
        tzinfo=timezone.utc,
    )

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        datetime_availability=((start, end),),
    )

    assert employee.datetime_availability == ((start, end),)

def test_employee_supports_weekly_availability():
    monday = WeeklyAvailability(
        weekday=0,
        start_time=time(9, 0),
        end_time=time(17, 0),
    )

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(monday,),
    )

    assert employee.weekly_availability == (monday,)

def test_employee_supports_availability_exceptions():
    day_off = AvailabilityException(
        date=date(2026, 11, 30),
        available=False,
    )

    shorter_day = AvailabilityException(
        date=date(2026, 12, 1),
        available=True,
        intervals=((time(13, 0), time(17, 0)),),
    )

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        availability_exceptions=(day_off, shorter_day),
    )

    assert employee.availability_exceptions == (
        day_off,
        shorter_day,
    )


def test_duplicate_availability_exception_dates():
    exceptions = (
        AvailabilityException(date(2026, 11, 30), False),
        AvailabilityException(
            date(2026, 11, 30),
            True,
            ((time(9, 0), time(17, 0)),),
        ),
    )

    with pytest.raises(
        ValueError,
        match="Duplicate availability exception dates",
    ):
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=20,
            availability_exceptions=exceptions,
        )


@pytest.mark.parametrize(
    "available, intervals",
    [
        (True, ()),
        (False, ((time(9, 0), time(17, 0)),)),
        (True, ((time(17, 0), time(9, 0)),)),
        (True, ((time(9, 0, 30), time(17, 0)),)),
        (True, (("09:00", time(17, 0)),)),
    ],
)
def test_invalid_availability_exception_intervals(
    available,
    intervals,
):
    with pytest.raises(ValueError):
        AvailabilityException(
            date=date(2026, 11, 30),
            available=available,
            intervals=intervals,
        )

def test_employee_rejects_mixed_availability_models():
    with pytest.raises(
        ValueError,
        match="Cannot combine datetime availability",
    ):
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=20,
            datetime_availability=(
                (
                    datetime(
                        2026, 11, 30, 9,
                        tzinfo=timezone.utc,
                    ),
                    datetime(
                        2026, 11, 30, 17,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
            weekly_availability=(
                WeeklyAvailability(
                    0,
                    time(9),
                    time(17),
                ),
            ),
        )


def test_employee_rejects_datetime_with_exceptions():
    with pytest.raises(
        ValueError,
        match="Cannot combine datetime availability",
    ):
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=20,
            datetime_availability=(),
            availability_exceptions=(
                AvailabilityException(
                    date(2026, 11, 30),
                    False,
                ),
            ),
        )


def test_valid_outside_assignment():
    employees = [
        Employee(1, "Alice", frozenset({"server"}), 20),
    ]

    outside = (
        FixedAssignment(
            employee_id=1,
            shift=make_shift(100, -1, 15, 23, 1, "server"),
        ),
    )

    validate_scheduling_inputs(
        employees,
        [],
        outside_assignments=outside,
    )


def test_outside_assignment_unknown_employee():
    employees = [
        Employee(1, "Alice", frozenset({"server"}), 20),
    ]

    outside = (
        FixedAssignment(
            employee_id=99,
            shift=make_shift(100, -1, 15, 23, 1, "server"),
        ),
    )

    with pytest.raises(ValueError, match="unknown employee"):
        validate_scheduling_inputs(
            employees,
            [],
            outside_assignments=outside,
        )


def test_outside_assignment_conflicting_shift_id():
    employees = [
        Employee(1, "Alice", frozenset({"server"}), 20),
    ]

    planning_shift = make_shift(1, 0, 9, 13, 1, "server")

    outside = (
        FixedAssignment(
            employee_id=1,
            shift=make_shift(1, -1, 15, 23, 1, "server"),
        ),
    )

    with pytest.raises(ValueError, match="conflicts"):
        validate_scheduling_inputs(
            employees,
            [planning_shift],
            outside_assignments=outside,
        )


def test_fixed_assignment_rejects_invalid_employee_id():
    shift = make_shift(100, -1, 15, 23, 1, "server")

    with pytest.raises(ValueError):
        FixedAssignment(
            employee_id=0,
            shift=shift,
        )


def test_fixed_assignment_rejects_invalid_shift():
    with pytest.raises(ValueError):
        FixedAssignment(
            employee_id=1,
            shift="Sunday evening",
        )


def test_rejects_duplicate_outside_assignments():
    employees = [
        Employee(1, "Alice", frozenset({"server"}), 20),
    ]

    outside_shift = make_shift(
        100, -1, 15, 23, 1, "server"
    )

    outside = (
        FixedAssignment(1, outside_shift),
        FixedAssignment(1, outside_shift),
    )

    with pytest.raises(
        ValueError,
        match="Duplicate outside fixed assignment",
    ):
        validate_scheduling_inputs(
            employees,
            [],
            outside_assignments=outside,
        )


def test_allows_distinct_outside_assignments():
    employees = [
        Employee(1, "Alice", frozenset({"server"}), 20),
    ]

    outside = (
        FixedAssignment(
            1,
            make_shift(100, -2, 9, 13, 1, "server"),
        ),
        FixedAssignment(
            1,
            make_shift(101, -1, 15, 23, 1, "server"),
        ),
    )

    validate_scheduling_inputs(
        employees,
        [],
        outside_assignments=outside,
    )
