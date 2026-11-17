from datetime import datetime, timedelta, timezone
from optimizer.models import (
    DateTimeShift,
    Employee,
    ShiftRequirement,
)
from optimizer.solver import generate_schedule
from optimizer.validator import validate_schedule
from optimizer.models import SchedulingPolicy
from optimizer.repair import count_assignment_changes
from unittest.mock import patch
from ortools.sat.python import cp_model

BASE = datetime(2026, 11, 23, tzinfo=timezone.utc)


def make_employee(
    employee_id,
    target_minutes=None,
    max_hours=20,
):
    return Employee(
        id=employee_id,
        name=f"Employee {employee_id}",
        skills=frozenset({"server"}),
        max_hours=max_hours,
        target_minutes=target_minutes,
        datetime_availability=(
            (BASE, BASE + timedelta(days=7)),
        ),
    )


def make_shift(shift_id, day=0, start_hour=9, duration=4):
    start = BASE + timedelta(
        days=day,
        hours=start_hour,
    )

    return DateTimeShift(
        id=shift_id,
        starts_at=start,
        ends_at=start + timedelta(hours=duration),
        requirements=(ShiftRequirement("server", 1),),
    )


def assigned_minutes(employees, shifts, schedule):
    """Calculate actual assigned minutes by employee."""
    totals = {employee.id: 0 for employee in employees}

    for shift in shifts:
        duration = int(
            (shift.ends_at - shift.starts_at).total_seconds()
            // 60
        )

        for assigned_ids in schedule[shift.id].values():
            for employee_id in assigned_ids:
                totals[employee_id] += duration

    return totals


def test_solver_prefers_employee_target():
    employees = [
        make_employee(1, target_minutes=240),
        make_employee(2, target_minutes=0),
    ]
    shifts = [make_shift(1)]

    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"server": [1]}
    }
    assert result.objective_values["target_deviation_min"] == 0
    assert result.objective_values["max_deviation_min"] == 0


def test_total_target_deviation_has_priority_over_balance():
    employees = [
        make_employee(1, target_minutes=480),
        make_employee(2),
        make_employee(3),
    ]

    shifts = [
        make_shift(1, day=0),
        make_shift(2, day=1),
    ]

    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    totals = assigned_minutes(
        employees,
        shifts,
        result.assignments,
    )

    # Employee 1 must receive both shifts to achieve
    # zero deviation, even though employees 2 and 3
    # would otherwise benefit from receiving work.
    assert totals[1] == 480
    assert totals[2] == 0
    assert totals[3] == 0

    assert result.objective_values["target_deviation_min"] == 0
    assert result.objective_values["untargeted_gap_min"] == 0


def test_no_targets_preserves_old_fairness_behavior():
    employees = [
        make_employee(1),
        make_employee(2),
        make_employee(3),
    ]

    shifts = [
        make_shift(1, day=0),
        make_shift(2, day=1),
        make_shift(3, day=2),
    ]

    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    totals = assigned_minutes(
        employees,
        shifts,
        result.assignments,
    )

    assert sorted(totals.values()) == [240, 240, 240]

    assert result.objective_values == {
        "untargeted_gap_min": 0,
    }

    assert validate_schedule(
        employees,
        shifts,
        result.assignments,
    ) == []

def test_maximum_deviation_breaks_total_deviation_tie():
    employees = [
        make_employee(1, target_minutes=480),
        make_employee(2, target_minutes=480),
    ]

    shifts = [
        make_shift(1, day=0),
        make_shift(2, day=1),
    ]

    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    totals = assigned_minutes(
        employees, shifts, result.assignments
    )

    # Both employees receive 4 hours rather than one
    # receiving 8 hours and the other receiving none.
    assert sorted(totals.values()) == [240, 240]

    assert result.objective_values["target_deviation_min"] == 480
    assert result.objective_values["max_deviation_min"] == 240


def test_repair_prioritizes_disruption_over_targets():
    employees = [
        make_employee(1, target_minutes=0),
        make_employee(2, target_minutes=240),
    ]

    shifts = [make_shift(1)]

    original_schedule = {
        1: {"server": [1]},
    }

    result = generate_schedule(
        employees,
        shifts,
        original_schedule=original_schedule,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == original_schedule

    assert count_assignment_changes(
        original_schedule,
        result.assignments,
    ) == 0

    assert result.objective_values["disruption"] == 0
    assert result.objective_values["target_deviation_min"] == 480

def test_fairness_disabled_skips_target_optimization():
    employees = [
        make_employee(1, target_minutes=240),
        make_employee(2, target_minutes=0),
    ]

    result = generate_schedule(
        employees,
        [make_shift(1)],
        policy=SchedulingPolicy(fairness_enabled=False),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert result.objective_values == {}
    assert result.stage_statuses == {
        "feasibility": "OPTIMAL",
    }

def test_unachievable_targets_do_not_make_schedule_infeasible():
    employees = [
        make_employee(1, target_minutes=480),
        make_employee(2, target_minutes=480),
    ]

    shifts = [make_shift(1)]

    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Only 240 minutes of work exist, but employees
    # collectively prefer 960 minutes.
    assert result.objective_values["target_deviation_min"] == 720

def test_positive_lock_overrides_target_preference():
    employees = [
        make_employee(1, target_minutes=0),
        make_employee(2, target_minutes=240),
    ]

    result = generate_schedule(
        employees,
        [make_shift(1)],
        locked_assignments={1: {"server": [1]}},
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [1]}}
    assert result.objective_values["target_deviation_min"] == 480

def test_negative_lock_overrides_target_preference():
    employees = [
        make_employee(1, target_minutes=240),
        make_employee(2, target_minutes=0),
    ]

    result = generate_schedule(
        employees,
        [make_shift(1)],
        excluded_assignments={1: [1]},
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [2]}}
    assert result.objective_values["target_deviation_min"] == 480

def test_objective_metrics_match_returned_schedule():
    employees = [
        make_employee(1, target_minutes=480),
        make_employee(2, target_minutes=240),
        make_employee(3),
        make_employee(4),
    ]

    shifts = [
        make_shift(1, day=0),
        make_shift(2, day=1),
        make_shift(3, day=2),
    ]

    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    totals = assigned_minutes(
        employees,
        shifts,
        result.assignments,
    )

    deviations = [
        abs(totals[e.id] - e.target_minutes)
        for e in employees
        if e.target_minutes is not None
    ]

    untargeted = [
        totals[e.id]
        for e in employees
        if e.target_minutes is None
    ]

    assert result.objective_values["target_deviation_min"] == sum(
        deviations
    )

    assert result.objective_values["max_deviation_min"] == max(
        deviations
    )

    assert result.objective_values["untargeted_gap_min"] == (
        max(untargeted) - min(untargeted)
    )

def test_untargeted_balance_breaks_tie():
    employees = [
        make_employee(1, target_minutes=240),
        make_employee(2),
        make_employee(3),
    ]

    shifts = [
        make_shift(1, day=0),
        make_shift(2, day=1),
        make_shift(3, day=2),
    ]

    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    totals = assigned_minutes(
        employees,
        shifts,
        result.assignments,
    )

    assert totals[1] == 240
    assert sorted([totals[2], totals[3]]) == [240, 240]

    assert result.objective_values["target_deviation_min"] == 0
    assert result.objective_values["untargeted_gap_min"] == 0

def test_schedule_metrics_match_final_assignments():
    employees = [
        make_employee(1, target_minutes=480),
        make_employee(2, target_minutes=240),
        make_employee(3),
        make_employee(4),
    ]

    shifts = [
        make_shift(1, day=0),
        make_shift(2, day=1),
        make_shift(3, day=2),
    ]

    result = generate_schedule(employees, shifts)

    assert result.assignments is not None
    assert result.schedule_metrics is not None

    totals = assigned_minutes(
        employees,
        shifts,
        result.assignments,
    )

    deviations = [
        abs(totals[e.id] - e.target_minutes)
        for e in employees
        if e.target_minutes is not None
    ]

    assert result.schedule_metrics["target_deviation_min"] == sum(
        deviations
    )

    assert result.schedule_metrics["max_deviation_min"] == max(
        deviations
    )

    assert result.schedule_metrics["untargeted_gap_min"] == abs(
        totals[3] - totals[4]
    )


def test_schedule_metrics_exist_without_fairness_optimization():
    employees = [
        make_employee(1, target_minutes=240),
        make_employee(2, target_minutes=0),
    ]

    result = generate_schedule(
        employees,
        [make_shift(1)],
        policy=SchedulingPolicy(fairness_enabled=False),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert result.objective_values == {}

    # Metrics are measurements, even when fairness is disabled.
    assert result.schedule_metrics is not None
    assert result.schedule_metrics["target_deviation_min"] in (
        0, 480
    )


def test_timeout_fallback_preserves_schedule_metrics():
    employees = [
        make_employee(1, target_minutes=240),
        make_employee(2, target_minutes=0),
    ]
    shifts = [make_shift(1)]

    original_solve = cp_model.CpSolver.solve
    call_count = 0

    def controlled_solve(solver, model):
        nonlocal call_count
        call_count += 1

        if call_count == 2:
            return cp_model.UNKNOWN

        return original_solve(solver, model)

    with patch.object(
        cp_model.CpSolver,
        "solve",
        controlled_solve,
    ):
        result = generate_schedule(employees, shifts)

    assert call_count == 2
    assert result.status == "FEASIBLE"
    assert result.assignments is not None

    assert result.stage_statuses == {
        "target_deviation_min": "OPTIMAL",
    }

    assert result.objective_values == {
        "target_deviation_min": 0,
    }

    assert result.schedule_metrics == {
        "target_deviation_min": 0,
        "max_deviation_min": 0,
    }


def test_empty_schedule_reports_target_deviation():
    employees = [
        make_employee(1, target_minutes=600),
        make_employee(2, target_minutes=0),
        make_employee(3),
    ]

    result = generate_schedule(employees, [])

    assert result.status == "OPTIMAL"
    assert result.assignments == {}
    assert result.objective_values == {}
    assert result.stage_statuses == {
        "feasibility": "OPTIMAL",
    }

    assert result.schedule_metrics == {
        "target_deviation_min": 600,
        "max_deviation_min": 600,
    }
