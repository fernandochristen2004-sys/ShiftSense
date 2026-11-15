import pytest

from optimizer.models import Employee, Shift, SchedulingPolicy
from optimizer.input_validator import validate_scheduling_inputs


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
        Shift(1, 0, 9, 13, 1, "server"),
        Shift(1, 1, 9, 13, 1, "server"),
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
        Shift(
            id=1001,
            day=0,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        )
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