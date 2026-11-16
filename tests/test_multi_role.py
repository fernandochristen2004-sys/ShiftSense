from datetime import datetime, timezone
from optimizer.models import (
    DateTimeShift,
    Employee,
    SchedulingPolicy,
    ShiftRequirement,
)
from optimizer.repair import count_assignment_changes
from optimizer.solver import generate_schedule
from optimizer.validator import validate_schedule


def make_employee(employee_id, skills, available=True):
    """Create an employee for multi-role tests."""
    availability = (
        (
            datetime(2026, 11, 23, 9, tzinfo=timezone.utc),
            datetime(2026, 11, 23, 17, tzinfo=timezone.utc),
        ),
    ) if available else ()

    return Employee(
        id=employee_id,
        name=f"Employee {employee_id}",
        skills=frozenset(skills),
        max_hours=8,
        datetime_availability=availability,
    )


def make_multi_role_shift(
    cook_count=2,
    server_count=1,
):
    """Create a shift requiring cooks and servers."""
    return DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 23, 9, tzinfo=timezone.utc
        ),
        ends_at=datetime(
            2026, 11, 23, 13, tzinfo=timezone.utc
        ),
        requirements=(
            ShiftRequirement("cook", cook_count),
            ShiftRequirement("server", server_count),
        ),
    )


def test_shift_supports_multiple_roles():
    employees = [
        make_employee(1, {"cook"}),
        make_employee(2, {"cook"}),
        make_employee(3, {"server"}),
    ]
    shift = make_multi_role_shift()

    result = generate_schedule(employees, [shift])

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert set(result.assignments[1]) == {"cook", "server"}
    assert set(result.assignments[1]["cook"]) == {1, 2}
    assert result.assignments[1]["server"] == [3]


def test_dual_skilled_employee_cannot_fill_two_roles():
    employees = [
        make_employee(1, {"cook", "server"}),
        make_employee(2, {"cook"}),
    ]
    shift = make_multi_role_shift(
        cook_count=1,
        server_count=1,
    )

    result = generate_schedule(employees, [shift])

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    assigned_ids = (
        result.assignments[1]["cook"]
        + result.assignments[1]["server"]
    )

    assert len(assigned_ids) == 2
    assert len(set(assigned_ids)) == 2


def test_insufficient_qualified_cooks_is_infeasible():
    employees = [
        make_employee(1, {"cook"}),
        make_employee(2, {"server"}),
        make_employee(3, {"server"}),
    ]

    result = generate_schedule(
        employees,
        [make_multi_role_shift()],
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_multi_role_assignments_match_qualifications():
    employees = [
        make_employee(1, {"cook"}),
        make_employee(2, {"cook", "server"}),
        make_employee(3, {"server"}),
    ]
    shift = make_multi_role_shift()

    result = generate_schedule(employees, [shift])

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    employee_by_id = {
        employee.id: employee
        for employee in employees
    }

    for skill, assigned_ids in result.assignments[1].items():
        for employee_id in assigned_ids:
            assert skill in employee_by_id[employee_id].skills


def test_repair_preserves_unchanged_roles():
    employees = [
        make_employee(1, {"cook"}),
        make_employee(2, {"cook"}, available=False),
        make_employee(3, {"server"}),
        make_employee(4, {"cook"}),
    ]
    shift = make_multi_role_shift()

    original_schedule = {
        1: {
            "cook": [1, 2],
            "server": [3],
        },
    }

    result = generate_schedule(
        employees,
        [shift],
        original_schedule=original_schedule,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert set(result.assignments[1]["cook"]) == {1, 4}
    assert result.assignments[1]["server"] == [3]

    assert count_assignment_changes(
        original_schedule,
        result.assignments,
    ) == 2


def test_role_change_costs_one():
    original_schedule = {
        1: {
            "cook": [1],
            "server": [2],
        },
    }

    repaired_schedule = {
        1: {
            "cook": [2],
            "server": [1],
        },
    }

    assert count_assignment_changes(
        original_schedule,
        repaired_schedule,
    ) == 2


def test_repair_minimizes_role_changes():
    employees = [
        make_employee(1, {"cook", "server"}),
        make_employee(2, {"cook", "server"}),
        make_employee(3, {"cook", "server"}),
    ]
    shift = make_multi_role_shift(
        cook_count=1,
        server_count=1,
    )

    original_schedule = {
        1: {
            "cook": [1],
            "server": [2],
        },
    }

    result = generate_schedule(
        employees,
        [shift],
        original_schedule=original_schedule,
        policy=SchedulingPolicy(fairness_enabled=False),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == original_schedule
    assert count_assignment_changes(
        original_schedule,
        result.assignments,
    ) == 0


def test_validator_rejects_duplicate_across_roles():
    employees = [
        make_employee(1, {"cook", "server"}),
        make_employee(2, {"cook"}),
    ]
    shift = make_multi_role_shift(
        cook_count=1,
        server_count=1,
    )

    invalid_schedule = {
        1: {
            "cook": [1],
            "server": [1],
        },
    }

    errors = validate_schedule(
        employees,
        [shift],
        invalid_schedule,
    )

    assert any(
        "duplicate employee assignments" in error
        for error in errors
    )


def test_multi_role_schedule_passes_validator():
    employees = [
        make_employee(1, {"cook"}),
        make_employee(2, {"cook"}),
        make_employee(3, {"server"}),
    ]
    shift = make_multi_role_shift()

    result = generate_schedule(employees, [shift])

    assert result.assignments is not None
    assert validate_schedule(
        employees,
        [shift],
        result.assignments,
    ) == []


def test_single_employee_role_change_costs_one():
    original_schedule = {
        1: {
            "cook": [1],
            "server": [],
        },
    }

    repaired_schedule = {
        1: {
            "cook": [],
            "server": [1],
        },
    }

    assert count_assignment_changes(
        original_schedule,
        repaired_schedule,
    ) == 1


def test_repair_prefers_role_change_over_replacement():
    employees = [
        make_employee(1, {"server"}),
        make_employee(2, {"cook", "server"}),
        make_employee(3, {"cook"}),
        make_employee(4, {"server"}),
    ]

    shift = make_multi_role_shift(
        cook_count=1,
        server_count=1,
    )

    # Employee 1 was originally a cook but can now only
    # work as a server. Employee 2 can move to cook.
    original_schedule = {
        1: {
            "cook": [1],
            "server": [2],
        },
    }

    result = generate_schedule(
        employees,
        [shift],
        original_schedule=original_schedule,
        policy=SchedulingPolicy(fairness_enabled=False),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {
            "cook": [2],
            "server": [1],
        },
    }

    # Two role changes cost 2 in total.
    assert count_assignment_changes(
        original_schedule,
        result.assignments,
    ) == 2


def test_one_employee_cannot_cover_two_required_roles():
    employees = [
        make_employee(1, {"cook", "server"}),
    ]

    shift = make_multi_role_shift(
        cook_count=1,
        server_count=1,
    )

    result = generate_schedule(employees, [shift])

    assert result.status == "INFEASIBLE"
    assert result.assignments is None
