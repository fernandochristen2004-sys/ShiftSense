import pytest
from optimizer.models import (
    ShiftRequirement,
    SchedulingPolicy,
    StaffingShortage,
    Employee,
    DateTimeShift,
    FixedAssignment,
)
from datetime import datetime, timezone, timedelta
from optimizer.solver import generate_schedule
from optimizer.coverage_metrics import calculate_coverage
from optimizer.validator import validate_schedule
from optimizer.repair import count_assignment_changes
from unittest.mock import patch
from ortools.sat.python import cp_model

def test_existing_requirement_defaults_to_exact_staffing():
    requirement = ShiftRequirement("server", 3)

    assert requirement.count == 3
    assert requirement.target_count == 3
    assert requirement.effective_min_count == 3
    assert requirement.min_count is None


def test_requirement_supports_lower_minimum():
    requirement = ShiftRequirement(
        "server", 3, min_count=2
    )

    assert requirement.target_count == 3
    assert requirement.effective_min_count == 2


def test_requirement_allows_zero_minimum():
    requirement = ShiftRequirement(
        "server", 3, min_count=0
    )

    assert requirement.effective_min_count == 0


@pytest.mark.parametrize(
    "invalid_minimum",
    [-1, 4, 1.5, True, "2"],
)
def test_requirement_rejects_invalid_minimum(
    invalid_minimum,
):
    with pytest.raises(ValueError):
        ShiftRequirement(
            "server",
            3,
            min_count=invalid_minimum,
        )


def test_partial_coverage_disabled_by_default():
    policy = SchedulingPolicy()

    assert policy.allow_partial_coverage is False


def test_partial_coverage_can_be_enabled():
    policy = SchedulingPolicy(
        allow_partial_coverage=True
    )

    assert policy.allow_partial_coverage is True


@pytest.mark.parametrize(
    "invalid_value",
    [1, 0, "yes", None],
)
def test_partial_coverage_rejects_invalid_policy(
    invalid_value,
):
    with pytest.raises(ValueError):
        SchedulingPolicy(
            allow_partial_coverage=invalid_value
        )


def test_staffing_shortage_stores_missing_positions():
    shortage = StaffingShortage(
        shift_id=1,
        role="server",
        missing=1,
    )

    assert shortage.shift_id == 1
    assert shortage.role == "server"
    assert shortage.missing == 1


def test_solver_minimizes_shortage_when_partial_enabled():
    start = datetime(2026, 11, 23, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=((start, end),),
        )
        for employee_id in (1, 2)
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=start,
            ends_at=end,
            requirements=(
                ShiftRequirement("server", 3, min_count=2),
            ),
        )
    ]

    result = generate_schedule(
        employees,
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"server": [1, 2]},
    }
    assert result.objective_values["coverage_shortage"] == 1
    assert result.stage_statuses["coverage_shortage"] == "OPTIMAL"
    assert result.fully_covered is False
    assert result.shortages == (
        StaffingShortage(shift_id=1, role="server", missing=1),
    )
    assert result.assignment_changes is None


def test_coverage_reports_one_missing_server():
    shift = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 23, 11, tzinfo=timezone.utc
        ),
        ends_at=datetime(
            2026, 11, 23, 15, tzinfo=timezone.utc
        ),
        requirements=(
            ShiftRequirement("server", 3, min_count=2),
        ),
    )

    fully_covered, shortages = calculate_coverage(
        [shift],
        {1: {"server": [1, 2]}},
    )

    assert fully_covered is False
    assert shortages == (
        StaffingShortage(shift_id=1, role="server", missing=1),
    )


def test_coverage_reports_fully_staffed_schedule():
    shift = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 23, 11, tzinfo=timezone.utc
        ),
        ends_at=datetime(
            2026, 11, 23, 15, tzinfo=timezone.utc
        ),
        requirements=(
            ShiftRequirement("server", 2),
        ),
    )

    fully_covered, shortages = calculate_coverage(
        [shift],
        {1: {"server": [1, 2]}},
    )

    assert fully_covered is True
    assert shortages == ()


def test_empty_schedule_is_fully_covered():
    assert calculate_coverage([], {}) == (True, ())


def make_coverage_test_data():
    start = datetime(2026, 11, 23, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=((start, end),),
        )
        for employee_id in (1, 2, 3, 4)
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=start,
            ends_at=end,
            requirements=(
                ShiftRequirement("server", 3, min_count=2),
            ),
        )
    ]

    return employees, shifts


def test_validator_accepts_shortage_when_partial_enabled():
    employees, shifts = make_coverage_test_data()
    schedule = {1: {"server": [1, 2]}}

    policy = SchedulingPolicy(allow_partial_coverage=True)

    errors = validate_schedule(
        employees, shifts, schedule, policy=policy
    )

    assert errors == []


def test_validator_rejects_shortage_when_partial_disabled():
    employees, shifts = make_coverage_test_data()
    schedule = {1: {"server": [1, 2]}}

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
        policy=SchedulingPolicy(allow_partial_coverage=False),
    )

    assert any("expected 3 employees" in error for error in errors)


def test_validator_rejects_below_minimum():
    employees, shifts = make_coverage_test_data()
    schedule = {1: {"server": [1]}}

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
        policy=SchedulingPolicy(allow_partial_coverage=True),
    )

    assert any("between 2 and 3" in error for error in errors)


def test_validator_rejects_overstaffing():
    employees, shifts = make_coverage_test_data()
    schedule = {1: {"server": [1, 2, 3, 4]}}

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
        policy=SchedulingPolicy(allow_partial_coverage=True),
    )

    assert any("between 2 and 3" in error for error in errors)


def test_validator_accepts_fully_covered_schedule():
    employees, shifts = make_coverage_test_data()
    schedule = {1: {"server": [1, 2, 3]}}

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
        policy=SchedulingPolicy(allow_partial_coverage=True),
    )

    assert errors == []


def test_repair_prioritizes_coverage_over_disruption():
    start = datetime(2026, 11, 23, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=((start, end),),
        )
        for employee_id in (1, 2)
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=start,
            ends_at=end,
            requirements=(
                ShiftRequirement("server", 2, min_count=1),
            ),
        )
    ]

    original_schedule = {
        1: {"server": [1]},
    }

    result = generate_schedule(
        employees,
        shifts,
        original_schedule=original_schedule,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"server": [1, 2]},
    }

    assert result.fully_covered is True
    assert result.shortages == ()

    assert result.objective_values["coverage_shortage"] == 0
    assert result.objective_values["disruption"] == 1

    assert result.stage_statuses["coverage_shortage"] == "OPTIMAL"
    assert result.stage_statuses["disruption"] == "OPTIMAL"


def test_repair_moves_employee_to_improve_coverage():
    day = datetime(2026, 11, 23, tzinfo=timezone.utc)

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=day.replace(hour=11),
            ends_at=day.replace(hour=15),
            requirements=(
                ShiftRequirement("server", 2, min_count=1),
            ),
        ),
        DateTimeShift(
            id=2,
            starts_at=day.replace(hour=12),
            ends_at=day.replace(hour=16),
            requirements=(
                ShiftRequirement("server", 2, min_count=1),
            ),
        ),
    ]

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=(
                (day.replace(hour=10), day.replace(hour=17)),
            ),
        )
        for employee_id in (1, 2, 3)
    ]

    original_schedule = {
        1: {"server": [1, 2]},
        2: {"server": [3]},
    }

    result = generate_schedule(
        employees,
        shifts,
        original_schedule=original_schedule,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Only three employees are available for two overlapping
    # shifts requiring four total positions.
    assert result.fully_covered is False
    assert sum(
        shortage.missing for shortage in result.shortages
    ) == 1

    assert result.objective_values["coverage_shortage"] == 1
    assert result.objective_values["disruption"] == 0

    # The original assignments already achieve the best
    # possible coverage, so no reassignment is necessary.
    assert result.assignments == original_schedule


def test_repair_reassigns_employee_to_meet_minimum():
    day = datetime(2026, 11, 23, tzinfo=timezone.utc)

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=day.replace(hour=11),
            ends_at=day.replace(hour=15),
            requirements=(
                ShiftRequirement("server", 2, min_count=1),
            ),
        ),
        DateTimeShift(
            id=2,
            starts_at=day.replace(hour=12),
            ends_at=day.replace(hour=16),
            requirements=(
                ShiftRequirement("server", 2, min_count=1),
            ),
        ),
    ]

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=(
                (day.replace(hour=10), day.replace(hour=17)),
            ),
        )
        for employee_id in (1, 2)
    ]

    original_schedule = {
        1: {"server": [1, 2]},
        2: {"server": []},
    }

    result = generate_schedule(
        employees,
        shifts,
        original_schedule=original_schedule,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Both shifts must meet their hard minimum.
    assert len(result.assignments[1]["server"]) == 1
    assert len(result.assignments[2]["server"]) == 1

    # One position remains unfilled on each shift.
    assert result.fully_covered is False
    assert sum(
        shortage.missing for shortage in result.shortages
    ) == 2

    assert result.objective_values["coverage_shortage"] == 2
    assert result.objective_values["disruption"] == 2


def test_repair_moves_employee_to_eliminate_shortage():
    day = datetime(2026, 11, 23, tzinfo=timezone.utc)

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=day.replace(hour=11),
            ends_at=day.replace(hour=15),
            requirements=(
                ShiftRequirement("server", 2, min_count=1),
            ),
        ),
        DateTimeShift(
            id=2,
            starts_at=day.replace(hour=12),
            ends_at=day.replace(hour=16),
            requirements=(
                ShiftRequirement("server", 2, min_count=1),
            ),
        ),
    ]

    availability = {
        1: ((day.replace(hour=10), day.replace(hour=17)),),
        2: ((day.replace(hour=11), day.replace(hour=15)),),
        3: ((day.replace(hour=11), day.replace(hour=15)),),
        4: ((day.replace(hour=12), day.replace(hour=16)),),
    }

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=availability[employee_id],
        )
        for employee_id in (1, 2, 3, 4)
    ]

    original_schedule = {
        1: {"server": [1, 2]},
        2: {"server": [4]},
    }

    result = generate_schedule(
        employees,
        shifts,
        original_schedule=original_schedule,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    assert result.assignments == {
        1: {"server": [2, 3]},
        2: {"server": [1, 4]},
    }

    assert result.fully_covered is True
    assert result.shortages == ()
    assert result.objective_values["coverage_shortage"] == 0
    assert result.objective_values["disruption"] == 3

    actual_changes = count_assignment_changes(
        original_schedule,
        result.assignments,
    )

    assert actual_changes == 3
    assert actual_changes == result.objective_values["disruption"]
    assert result.assignment_changes == 3
    assert result.assignment_changes == count_assignment_changes(
        original_schedule,
        result.assignments,
    )

def test_solver_rejects_shortage_when_partial_disabled():
    employees, shifts = make_coverage_test_data()

    result = generate_schedule(
        employees[:2],
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=False,
            fairness_enabled=False,
        ),
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None
    assert result.fully_covered is None
    assert result.shortages == ()


def test_solver_rejects_staffing_below_hard_minimum():
    employees, shifts = make_coverage_test_data()

    result = generate_schedule(
        employees[:1],
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None
    assert result.fully_covered is None
    assert result.shortages == ()


def test_partial_coverage_respects_positive_lock():
    employees, shifts = make_coverage_test_data()

    result = generate_schedule(
        employees[:2],
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
        locked_assignments={
            1: {"server": [1]},
        },
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert 1 in result.assignments[1]["server"]

    assert result.fully_covered is False
    assert result.shortages == (
        StaffingShortage(1, "server", 1),
    )


def test_partial_coverage_respects_negative_lock():
    employees, shifts = make_coverage_test_data()

    result = generate_schedule(
        employees[:3],
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
        excluded_assignments={
            1: [3],
        },
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert 3 not in result.assignments[1]["server"]

    assert result.fully_covered is False
    assert result.shortages == (
        StaffingShortage(1, "server", 1),
    )


def test_partial_coverage_respects_minimum_rest():
    day = datetime(2026, 11, 23, tzinfo=timezone.utc)

    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(
                (day, day + timedelta(days=2)),
            ),
        )
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=day + timedelta(hours=17),
            ends_at=day + timedelta(hours=23),
            requirements=(
                ShiftRequirement("server", 1, min_count=0),
            ),
        ),
        DateTimeShift(
            id=2,
            starts_at=day + timedelta(days=1, hours=7),
            ends_at=day + timedelta(days=1, hours=11),
            requirements=(
                ShiftRequirement("server", 1, min_count=0),
            ),
        ),
    ]

    policy = SchedulingPolicy(
        allow_partial_coverage=True,
        fairness_enabled=False,
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    result = generate_schedule(
        employees,
        shifts,
        policy=policy,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # The employee cannot work both shifts (only 8h rest).
    assigned_count = sum(
        len(result.assignments[shift.id]["server"])
        for shift in shifts
    )

    assert assigned_count == 1
    assert sum(s.missing for s in result.shortages) == 1

    assert validate_schedule(
        employees,
        shifts,
        result.assignments,
        policy=policy,
    ) == []


def test_partial_coverage_allows_valid_split_shifts():
    day = datetime(2026, 11, 23, tzinfo=timezone.utc)

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=12,
        datetime_availability=(
            (day, day + timedelta(days=1)),
        ),
    )

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=day + timedelta(hours=11),
            ends_at=day + timedelta(hours=15),
            requirements=(
                ShiftRequirement("server", 1, min_count=0),
            ),
        ),
        DateTimeShift(
            id=2,
            starts_at=day + timedelta(hours=17),
            ends_at=day + timedelta(hours=23),
            requirements=(
                ShiftRequirement("server", 1, min_count=0),
            ),
        ),
    ]

    policy = SchedulingPolicy(
        allow_partial_coverage=True,
        fairness_enabled=False,
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
        allow_split_shifts=True,
        split_shift_min_break_minutes=120,
        max_split_span_minutes=780,
    )

    result = generate_schedule(
        [employee],
        shifts,
        policy=policy,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"server": [1]},
        2: {"server": [1]},
    }

    assert result.fully_covered is True
    assert result.shortages == ()

    assert validate_schedule(
        [employee],
        shifts,
        result.assignments,
        policy=policy,
    ) == []


def test_partial_coverage_respects_outside_assignment():
    day = datetime(2026, 11, 23, tzinfo=timezone.utc)

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=12,
        datetime_availability=(
            (day, day + timedelta(days=1)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=day + timedelta(hours=11),
        ends_at=day + timedelta(hours=15),
        requirements=(
            ShiftRequirement("server", 1, min_count=0),
        ),
    )

    outside = FixedAssignment(
        employee_id=1,
        shift=DateTimeShift(
            id=100,
            starts_at=day + timedelta(hours=10),
            ends_at=day + timedelta(hours=14),
            requirements=(ShiftRequirement("server", 1),),
        ),
    )

    policy = SchedulingPolicy(
        allow_partial_coverage=True,
        fairness_enabled=False,
    )

    result = generate_schedule(
        [employee],
        [shift],
        policy=policy,
        outside_assignments=(outside,),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": []}}
    assert result.fully_covered is False
    assert result.shortages == (
        StaffingShortage(1, "server", 1),
    )

    assert validate_schedule(
        [employee],
        [shift],
        result.assignments,
        policy=policy,
        outside_assignments=(outside,),
    ) == []


def test_partial_coverage_allows_valid_outside_split():
    day = datetime(2026, 11, 23, tzinfo=timezone.utc)

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=12,
        datetime_availability=(
            (day, day + timedelta(days=1)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=day + timedelta(hours=17),
        ends_at=day + timedelta(hours=23),
        requirements=(
            ShiftRequirement("server", 1, min_count=0),
        ),
    )

    outside = FixedAssignment(
        employee_id=1,
        shift=DateTimeShift(
            id=100,
            starts_at=day + timedelta(hours=11),
            ends_at=day + timedelta(hours=15),
            requirements=(ShiftRequirement("server", 1),),
        ),
    )

    policy = SchedulingPolicy(
        allow_partial_coverage=True,
        fairness_enabled=False,
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
        allow_split_shifts=True,
    )

    result = generate_schedule(
        [employee],
        [shift],
        policy=policy,
        outside_assignments=(outside,),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [1]}}
    assert result.fully_covered is True
    assert result.shortages == ()

    assert validate_schedule(
        [employee],
        [shift],
        result.assignments,
        policy=policy,
        outside_assignments=(outside,),
    ) == []


def test_coverage_takes_priority_over_target_fairness():
    start = datetime(2026, 11, 23, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            target_minutes=0,
            datetime_availability=((start, end),),
        )
        for employee_id in (1, 2)
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=start,
            ends_at=end,
            requirements=(
                ShiftRequirement("server", 2, min_count=0),
            ),
        )
    ]

    result = generate_schedule(
        employees,
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=True,
        ),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"server": [1, 2]},
    }

    assert result.fully_covered is True
    assert result.shortages == ()

    assert result.objective_values["coverage_shortage"] == 0
    assert result.objective_values["target_deviation_min"] == 480

    assert result.stage_statuses["coverage_shortage"] == "OPTIMAL"


def test_partial_coverage_retained_after_later_stage_timeout():
    start = datetime(2026, 11, 23, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            target_minutes=0,
            datetime_availability=((start, end),),
        )
        for employee_id in (1, 2)
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=start,
            ends_at=end,
            requirements=(
                ShiftRequirement("server", 3, min_count=2),
            ),
        )
    ]

    original_schedule = {
        1: {"server": [1]},
    }

    policy = SchedulingPolicy(
        allow_partial_coverage=True,
        fairness_enabled=True,
    )

    original_solve = cp_model.CpSolver.solve
    solve_calls = 0

    def simulate_timeout(solver, model):
        nonlocal solve_calls
        solve_calls += 1

        # Coverage and disruption succeed.
        # Simulate a timeout before fairness finds a solution.
        if solve_calls == 3:
            return cp_model.UNKNOWN

        return original_solve(solver, model)

    with patch.object(
        cp_model.CpSolver,
        "solve",
        simulate_timeout,
    ):
        result = generate_schedule(
            employees,
            shifts,
            original_schedule=original_schedule,
            policy=policy,
        )

    assert solve_calls == 3
    assert result.status == "FEASIBLE"
    assert result.assignments == {
        1: {"server": [1, 2]},
    }

    assert result.fully_covered is False
    assert result.shortages == (
        StaffingShortage(1, "server", 1),
    )

    assert result.assignment_changes == 1

    assert result.objective_values["coverage_shortage"] == 1
    assert result.objective_values["disruption"] == 1

    assert "target_deviation_min" not in result.objective_values

    assert result.stage_statuses == {
        "coverage_shortage": "OPTIMAL",
        "disruption": "OPTIMAL",
    }

    assert result.schedule_metrics["target_deviation_min"] == 480

    assert validate_schedule(
        employees,
        shifts,
        result.assignments,
        policy=policy,
    ) == []


def test_partial_coverage_rejects_locks_above_target():
    employees, _ = make_coverage_test_data()

    start = datetime(2026, 11, 23, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)

    shift = DateTimeShift(
        id=1,
        starts_at=start,
        ends_at=end,
        requirements=(
            ShiftRequirement("server", 2, min_count=1),
        ),
    )

    with pytest.raises(
        ValueError,
        match="locked assignments exceed staffing requirements",
    ):
        generate_schedule(
            employees[:3],
            [shift],
            policy=SchedulingPolicy(
                allow_partial_coverage=True,
            ),
            locked_assignments={
                1: {"server": [1, 2, 3]},
            },
        )


def test_exact_staffing_reports_full_coverage():
    employees, shifts = make_coverage_test_data()

    result = generate_schedule(
        employees[:3],
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=False,
            fairness_enabled=False,
        ),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert result.fully_covered is True
    assert result.shortages == ()
    assert result.assignment_changes is None


def test_partial_coverage_without_minimum_still_requires_target():
    start = datetime(2026, 11, 23, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=8,
        datetime_availability=((start, end),),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=start,
        ends_at=end,
        requirements=(
            ShiftRequirement("server", 2),
        ),
    )

    result = generate_schedule(
        [employee],
        [shift],
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None
    assert result.fully_covered is None
    assert result.shortages == ()
