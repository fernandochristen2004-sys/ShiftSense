from datetime import datetime, timedelta, timezone

import pytest

from optimizer.models import (
    DateTimeShift,
    Employee,
    FixedAssignment,
    SchedulingPolicy,
    ShiftRequirement,
)
from optimizer.solver import generate_schedule
from optimizer.validator import validate_schedule


def make_employee(employee_id, skills=("cook", "server"), max_hours=16,
                  available=True):
    availability = (
        (
            datetime(2026, 11, 23, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 26, 0, tzinfo=timezone.utc),
        ),
    ) if available else ()

    return Employee(
        id=employee_id,
        name=f"Employee {employee_id}",
        skills=frozenset(skills),
        max_hours=max_hours,
        datetime_availability=availability,
    )


def make_shift(shift_id=1, day=0, start_hour=9, end_hour=13,
               requirements=None):
    if requirements is None:
        requirements = (
            ShiftRequirement("cook", 1),
            ShiftRequirement("server", 1),
        )

    base = datetime(2026, 11, 23, tzinfo=timezone.utc)

    return DateTimeShift(
        id=shift_id,
        starts_at=base + timedelta(days=day, hours=start_hour),
        ends_at=base + timedelta(days=day, hours=end_hour),
        requirements=requirements,
    )


def test_locked_assignment_is_preserved():
    employees = [make_employee(1), make_employee(2)]
    shift = make_shift()
    locks = {1: {"cook": [1]}}

    result = generate_schedule(
        employees, [shift], locked_assignments=locks
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert result.assignments[1]["cook"] == [1]
    assert result.assignments[1]["server"] == [2]


def test_unlocked_positions_can_be_filled():
    employees = [
        make_employee(1, skills=("cook",)),
        make_employee(2, skills=("server",)),
        make_employee(3, skills=("server",)),
    ]
    shift = make_shift(
        requirements=(
            ShiftRequirement("cook", 1),
            ShiftRequirement("server", 2),
        )
    )

    result = generate_schedule(
        employees,
        [shift],
        locked_assignments={1: {"cook": [1]}},
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"cook": [1], "server": [2, 3]}
    }


@pytest.mark.parametrize(
    "locks",
    [
        {99: {"cook": [1]}},
        {1: {"manager": [1]}},
        {1: {"cook": [99]}},
        {1: {"cook": [1, 1]}},
        {1: {"cook": [1], "server": [1]}},
        {1: {"cook": [1, 2]}},
        {1: {"cook": "Alice"}},
    ],
)
def test_invalid_locked_assignments_raise_value_error(locks):
    employees = [make_employee(1), make_employee(2)]
    shift = make_shift()

    with pytest.raises(ValueError):
        generate_schedule(
            employees,
            [shift],
            locked_assignments=locks,
        )


def test_unavailable_locked_employee_is_infeasible():
    employees = [
        make_employee(1, available=False),
        make_employee(2),
        make_employee(3),
    ]

    result = generate_schedule(
        employees,
        [make_shift()],
        locked_assignments={1: {"cook": [1]}},
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_unqualified_locked_employee_is_infeasible():
    employees = [
        make_employee(1, skills=("server",)),
        make_employee(2),
        make_employee(3),
    ]

    result = generate_schedule(
        employees,
        [make_shift()],
        locked_assignments={1: {"cook": [1]}},
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_overlapping_locked_shifts_are_infeasible():
    employees = [
        make_employee(1),
        make_employee(2),
        make_employee(3),
    ]
    shifts = [
        make_shift(1, 0, 9, 13),
        make_shift(2, 0, 12, 16),
    ]

    result = generate_schedule(
        employees,
        shifts,
        locked_assignments={
            1: {"cook": [1]},
            2: {"server": [1]},
        },
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_locked_assignments_respect_maximum_hours():
    employees = [
        make_employee(1, max_hours=4),
        make_employee(2),
        make_employee(3),
    ]
    shifts = [
        make_shift(1, 0, 9, 13),
        make_shift(2, 1, 9, 13),
    ]

    result = generate_schedule(
        employees,
        shifts,
        locked_assignments={
            1: {"cook": [1]},
            2: {"cook": [1]},
        },
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_locked_assignments_respect_minimum_rest():
    employees = [
        make_employee(1),
        make_employee(2),
        make_employee(3),
    ]
    shifts = [
        make_shift(1, 0, 17, 23),
        make_shift(2, 1, 7, 11),
    ]

    result = generate_schedule(
        employees,
        shifts,
        policy=SchedulingPolicy(
            minimum_rest_hours=11,
            enforce_minimum_rest=True,
        ),
        locked_assignments={
            1: {"cook": [1]},
            2: {"server": [1]},
        },
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_locked_assignment_conflicts_with_outside_shift():
    employees = [
        make_employee(1),
        make_employee(2),
    ]
    shift = make_shift()

    outside = FixedAssignment(
        employee_id=1,
        shift=make_shift(
            shift_id=100,
            start_hour=10,
            end_hour=14,
        ),
    )

    result = generate_schedule(
        employees,
        [shift],
        outside_assignments=(outside,),
        locked_assignments={1: {"cook": [1]}},
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_repair_cannot_override_locked_assignment():
    employees = [
        make_employee(1),
        make_employee(2),
        make_employee(3),
    ]
    shift = make_shift()

    original_schedule = {
        1: {
            "cook": [1],
            "server": [2],
        }
    }

    result = generate_schedule(
        employees,
        [shift],
        original_schedule=original_schedule,
        locked_assignments={1: {"cook": [3]}},
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert result.assignments[1]["cook"] == [3]


def test_validator_detects_missing_locked_employee():
    employees = [make_employee(1), make_employee(2)]
    shift = make_shift()

    schedule = {
        1: {
            "cook": [2],
            "server": [1],
        }
    }

    errors = validate_schedule(
        employees,
        [shift],
        schedule,
        locked_assignments={1: {"cook": [1]}},
    )

    assert any(
        "locked employee 1" in error
        for error in errors
    )


def test_validator_accepts_preserved_lock():
    employees = [make_employee(1), make_employee(2)]
    shift = make_shift()

    schedule = {
        1: {
            "cook": [1],
            "server": [2],
        }
    }

    assert validate_schedule(
        employees,
        [shift],
        schedule,
        locked_assignments={1: {"cook": [1]}},
    ) == []
