import pytest

from datetime import datetime, timezone
from optimizer.models import Employee, DateTimeShift, SchedulingPolicy
from optimizer.input_validator import validate_scheduling_inputs


def make_shift(shift_id, day, start_hour, end_hour, required_staff, required_skill):
    """Create a timezone-aware shift anchored to 23 November 2026."""
    from datetime import timedelta

    base = datetime(2026, 11, 23, tzinfo=timezone.utc)
    return DateTimeShift(
        id=shift_id,
        starts_at=base + timedelta(days=day, hours=start_hour),
        ends_at=base + timedelta(days=day, hours=end_hour),
        required_staff=required_staff,
        required_skill=required_skill,
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
