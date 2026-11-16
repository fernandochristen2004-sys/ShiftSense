from datetime import datetime, timezone

import pytest

from optimizer.models import (
    DateTimeShift,
    Employee,
    ShiftRequirement,
)
from optimizer.solver import generate_schedule
from optimizer.validator import validate_schedule


def make_employee(employee_id, skills=("cook", "server")):
    return Employee(
        id=employee_id,
        name=f"Employee {employee_id}",
        skills=frozenset(skills),
        max_hours=16,
        datetime_availability=(
            (
                datetime(2026, 11, 23, 9, tzinfo=timezone.utc),
                datetime(2026, 11, 23, 17, tzinfo=timezone.utc),
            ),
        ),
    )


def make_shift():
    return DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 23, 9, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 23, 13, tzinfo=timezone.utc),
        requirements=(
            ShiftRequirement("cook", 1),
            ShiftRequirement("server", 1),
        ),
    )


def test_excluded_employee_is_not_scheduled():
    employees = [
        make_employee(1),
        make_employee(2),
        make_employee(3),
    ]

    result = generate_schedule(
        employees,
        [make_shift()],
        excluded_assignments={1: [1]},
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    assigned_ids = (
        result.assignments[1]["cook"]
        + result.assignments[1]["server"]
    )

    assert 1 not in assigned_ids
    assert set(assigned_ids) == {2, 3}


def test_exclusion_can_make_schedule_infeasible():
    employees = [
        make_employee(1, skills=("cook",)),
        make_employee(2, skills=("server",)),
    ]

    result = generate_schedule(
        employees,
        [make_shift()],
        excluded_assignments={1: [1]},
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_positive_and_negative_locks_work_together():
    employees = [
        make_employee(1),
        make_employee(2),
        make_employee(3),
    ]

    result = generate_schedule(
        employees,
        [make_shift()],
        locked_assignments={1: {"cook": [1]}},
        excluded_assignments={1: [2]},
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {
            "cook": [1],
            "server": [3],
        }
    }


@pytest.mark.parametrize(
    "excluded_assignments",
    [
        {99: [1]},
        {1: [99]},
        {1: [1, 1]},
        {1: "Alice"},
        [1, 2],
    ],
)
def test_invalid_exclusions_raise_value_error(excluded_assignments):
    with pytest.raises(ValueError):
        generate_schedule(
            [make_employee(1), make_employee(2)],
            [make_shift()],
            excluded_assignments=excluded_assignments,
        )


def test_employee_cannot_be_locked_and_excluded():
    with pytest.raises(ValueError, match="both locked and excluded"):
        generate_schedule(
            [make_employee(1), make_employee(2)],
            [make_shift()],
            locked_assignments={1: {"cook": [1]}},
            excluded_assignments={1: [1]},
        )


def test_repair_respects_excluded_employee():
    employees = [
        make_employee(1),
        make_employee(2),
        make_employee(3),
    ]

    original_schedule = {
        1: {
            "cook": [1],
            "server": [2],
        }
    }

    result = generate_schedule(
        employees,
        [make_shift()],
        original_schedule=original_schedule,
        excluded_assignments={1: [1]},
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    assigned_ids = (
        result.assignments[1]["cook"]
        + result.assignments[1]["server"]
    )

    assert 1 not in assigned_ids


def test_validator_detects_excluded_employee():
    employees = [make_employee(1), make_employee(2)]
    schedule = {
        1: {
            "cook": [1],
            "server": [2],
        }
    }

    errors = validate_schedule(
        employees,
        [make_shift()],
        schedule,
        excluded_assignments={1: [1]},
    )

    assert any(
        "excluded employee 1" in error
        for error in errors
    )


def test_validator_accepts_respected_exclusion():
    employees = [make_employee(1), make_employee(2), make_employee(3)]
    schedule = {
        1: {
            "cook": [1],
            "server": [2],
        }
    }

    assert validate_schedule(
        employees,
        [make_shift()],
        schedule,
        excluded_assignments={1: [3]},
    ) == []
