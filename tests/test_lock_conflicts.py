from datetime import datetime, timedelta, timezone
import pytest
from optimizer.lock_conflicts import find_lock_conflicts
from optimizer.models import (
    DateTimeShift,
    Employee,
    FixedAssignment,
    SchedulingPolicy,
    ShiftRequirement,
)
from optimizer.solver import generate_schedule


BASE = datetime(2026, 11, 23, tzinfo=timezone.utc)


def make_employee(
    employee_id=1,
    skills=("cook",),
    max_hours=16,
    available=True,
):
    availability = (
        ((BASE, BASE + timedelta(days=4)),)
        if available
        else ()
    )

    return Employee(
        id=employee_id,
        name=f"Employee {employee_id}",
        skills=frozenset(skills),
        max_hours=max_hours,
        datetime_availability=availability,
    )


def make_shift(
    shift_id=1,
    day=0,
    start_hour=9,
    end_hour=13,
):
    return DateTimeShift(
        id=shift_id,
        starts_at=BASE + timedelta(
            days=day, hours=start_hour
        ),
        ends_at=BASE + timedelta(
            days=day, hours=end_hour
        ),
        requirements=(ShiftRequirement("cook", 1),),
    )


def diagnose(
    employees,
    shifts,
    locks,
    policy=None,
    outside_assignments=(),
):
    return find_lock_conflicts(
        employees=employees,
        shifts=shifts,
        locked_assignments=locks,
        policy=policy or SchedulingPolicy(),
        outside_assignments=outside_assignments,
    )


def test_unqualified_employee_conflict():
    conflicts = diagnose(
        [make_employee(skills=("server",))],
        [make_shift()],
        {1: {"cook": [1]}},
    )

    assert any("lacks" in message for message in conflicts)


def test_unavailable_employee_conflict():
    conflicts = diagnose(
        [make_employee(available=False)],
        [make_shift()],
        {1: {"cook": [1]}},
    )

    assert any("unavailable" in message for message in conflicts)


def test_overlapping_locked_shifts_conflict():
    shifts = [
        make_shift(1, start_hour=9, end_hour=13),
        make_shift(2, start_hour=12, end_hour=16),
    ]

    conflicts = diagnose(
        [make_employee()],
        shifts,
        {
            1: {"cook": [1]},
            2: {"cook": [1]},
        },
    )

    assert any("overlapping" in message for message in conflicts)


def test_minimum_rest_conflict():
    shifts = [
        make_shift(1, day=0, start_hour=17, end_hour=23),
        make_shift(2, day=1, start_hour=7, end_hour=11),
    ]

    conflicts = diagnose(
        [make_employee()],
        shifts,
        {
            1: {"cook": [1]},
            2: {"cook": [1]},
        },
        policy=SchedulingPolicy(
            minimum_rest_hours=11,
            enforce_minimum_rest=True,
        ),
    )

    assert any("minimum rest" in message for message in conflicts)


def test_maximum_hours_conflict():
    shifts = [
        make_shift(1, day=0),
        make_shift(2, day=1),
    ]

    conflicts = diagnose(
        [make_employee(max_hours=4)],
        shifts,
        {
            1: {"cook": [1]},
            2: {"cook": [1]},
        },
    )

    assert any("exceeding" in message for message in conflicts)


def test_outside_shift_overlap_conflict():
    outside = FixedAssignment(
        employee_id=1,
        shift=make_shift(
            shift_id=99,
            start_hour=10,
            end_hour=14,
        ),
    )

    conflicts = diagnose(
        [make_employee()],
        [make_shift()],
        {1: {"cook": [1]}},
        outside_assignments=(outside,),
    )

    assert any("outside Shift" in message for message in conflicts)


def test_outside_shift_rest_conflict():
    outside = FixedAssignment(
        employee_id=1,
        shift=make_shift(
            shift_id=99,
            day=0,
            start_hour=17,
            end_hour=23,
        ),
    )

    conflicts = diagnose(
        [make_employee()],
        [make_shift(day=1, start_hour=7, end_hour=11)],
        {1: {"cook": [1]}},
        policy=SchedulingPolicy(
            minimum_rest_hours=11,
            enforce_minimum_rest=True,
        ),
        outside_assignments=(outside,),
    )

    assert any("minimum rest" in message for message in conflicts)


def test_no_conflicts_for_valid_lock():
    conflicts = diagnose(
        [make_employee()],
        [make_shift()],
        {1: {"cook": [1]}},
    )

    assert conflicts == ()


def test_solver_returns_qualification_explanation():
    result = generate_schedule(
        [make_employee(skills=("server",))],
        [make_shift()],
        locked_assignments={1: {"cook": [1]}},
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None
    assert any("lacks" in message for message in result.conflicts)


def test_solver_returns_empty_conflicts_when_feasible():
    result = generate_schedule(
        [make_employee()],
        [make_shift()],
        locked_assignments={1: {"cook": [1]}},
    )

    assert result.status == "OPTIMAL"
    assert result.conflicts == ()


def test_solver_does_not_invent_conflict_reason():
    result = generate_schedule(
        [make_employee(skills=("server",))],
        [make_shift()],
    )

    assert result.status == "INFEASIBLE"
    assert result.conflicts == ()
