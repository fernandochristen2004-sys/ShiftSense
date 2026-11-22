"""End-to-end: generate a schedule, simulate a call-out, repair, validate."""

import pytest

from optimizer import engine
from optimizer.synthetic_data import (
    apply_callout,
    callout_window,
    generate_restaurant_scenario,
    pick_callout,
)


def _missing(result):
    return sum(shortage.missing for shortage in result.shortages)


def _assigned(assignments, shift_id, employee_id):
    return any(employee_id in ids for ids in assignments.get(shift_id, {}).values())


@pytest.fixture(scope="module", params=[(25, 42), (40, 42)], ids=["25-staff", "40-staff"])
def callout_run(request):
    """Generate a week, then repair the first recoverable call-out.

    Some call-outs can't be covered at all (for example, the only bartender
    that night), and repair correctly returns INFEASIBLE for those. These
    tests are about successful repairs, so up to 20 call-outs are tried.
    """
    size, seed = request.param
    scenario = generate_restaurant_scenario(size, seed=seed)
    shifts = list(scenario.shifts)

    original = engine.generate(
        employees=list(scenario.employees),
        shifts=shifts,
        policy=scenario.policy,
    )
    assert original.assignments is not None, "generation must succeed for this size"

    for callout_seed in range(20):
        shift_id, employee_id = pick_callout(original.assignments, seed=callout_seed)
        shift = next(s for s in shifts if s.id == shift_id)

        repaired = engine.repair(
            employees=apply_callout(scenario.employees, employee_id, shift),
            shifts=shifts,
            policy=scenario.policy,
            original_schedule=original.assignments,
        )

        if repaired.assignments is not None:
            return original, repaired, shift_id, employee_id, shifts

    pytest.fail("No recoverable call-out found in 20 attempts.")


def test_unrecoverable_callout_is_reported_cleanly():
    """When a call-out can't be covered, repair says so without a schedule."""
    scenario = generate_restaurant_scenario(25, seed=42)
    shifts = list(scenario.shifts)
    original = engine.generate(
        employees=list(scenario.employees),
        shifts=shifts,
        policy=scenario.policy,
    )

    for callout_seed in range(20):
        shift_id, employee_id = pick_callout(original.assignments, seed=callout_seed)
        shift = next(s for s in shifts if s.id == shift_id)
        repaired = engine.repair(
            employees=apply_callout(scenario.employees, employee_id, shift),
            shifts=shifts,
            policy=scenario.policy,
            original_schedule=original.assignments,
        )
        if repaired.assignments is None:
            assert repaired.status in ("INFEASIBLE", "UNKNOWN")
            assert repaired.fully_covered is None
            assert repaired.shortages == ()
            return

    pytest.skip("Every sampled call-out was recoverable for this restaurant.")


def test_original_schedule_is_valid(callout_run):
    original, _, _, _, _ = callout_run

    assert original.status in ("OPTIMAL", "FEASIBLE")
    assert original.validation_errors == ()


def test_repair_returns_a_valid_schedule(callout_run):
    _, repaired, _, _, _ = callout_run

    assert repaired.status in ("OPTIMAL", "FEASIBLE")
    assert repaired.assignments is not None
    assert repaired.validation_errors == ()
    assert repaired.fully_covered == (len(repaired.shortages) == 0)


def test_called_out_employee_is_removed_from_their_shift(callout_run):
    _, repaired, shift_id, employee_id, _ = callout_run

    assert not _assigned(repaired.assignments, shift_id, employee_id)


def test_called_out_employee_works_nothing_else_that_day(callout_run):
    """A call-out blocks the rest of the day, not just the one shift."""
    _, repaired, shift_id, employee_id, shifts = callout_run
    shift = next(s for s in shifts if s.id == shift_id)
    start, end = callout_window(shift)

    for other in shifts:
        if other.starts_at < end and start < other.ends_at:
            assert not _assigned(repaired.assignments, other.id, employee_id)


def test_repair_is_no_worse_than_just_removing_the_employee(callout_run):
    """Coverage comes first, so at most the one lost position stays unfilled."""
    original, repaired, _, _, _ = callout_run

    assert _missing(repaired) <= _missing(original) + 1


def test_repair_reports_at_least_the_removal_as_a_change(callout_run):
    _, repaired, _, _, _ = callout_run

    assert repaired.assignment_changes is not None
    assert repaired.assignment_changes >= 1


def test_repair_without_any_change_keeps_the_schedule():
    """Repairing a valid schedule with nothing changed should change nothing."""
    scenario = generate_restaurant_scenario(25, seed=42)
    employees, shifts = list(scenario.employees), list(scenario.shifts)

    original = engine.generate(employees=employees, shifts=shifts, policy=scenario.policy)
    assert original.assignments is not None

    repaired = engine.repair(
        employees=employees,
        shifts=shifts,
        policy=scenario.policy,
        original_schedule=original.assignments,
    )

    assert repaired.assignment_changes == 0
    assert _missing(repaired) == _missing(original)
    assert repaired.validation_errors == ()
