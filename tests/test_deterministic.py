"""Deterministic mode: the same input gives the same schedule."""

from ortools.sat.python import cp_model

from optimizer import engine
from optimizer.staged_solver import configure_solver
from optimizer.synthetic_data import (
    apply_callout,
    generate_restaurant_scenario,
    pick_callout,
)


def _generate(scenario, deterministic):
    return engine.generate(
        employees=list(scenario.employees),
        shifts=list(scenario.shifts),
        policy=scenario.policy,
        deterministic=deterministic,
    )


def test_configure_solver_default_keeps_parallel_search():
    solver = cp_model.CpSolver()
    default_workers = solver.parameters.num_workers

    configure_solver(solver, 5.0)

    assert solver.parameters.max_time_in_seconds == 5.0
    assert solver.parameters.num_workers == default_workers


def test_configure_solver_deterministic_uses_one_worker_and_fixed_seed():
    solver = cp_model.CpSolver()

    configure_solver(solver, 5.0, deterministic=True)

    assert solver.parameters.max_time_in_seconds == 5.0
    assert solver.parameters.num_workers == 1
    assert solver.parameters.random_seed == 0


def test_deterministic_generate_returns_the_same_schedule():
    scenario = generate_restaurant_scenario(25, seed=42)

    first = _generate(scenario, deterministic=True)
    second = _generate(scenario, deterministic=True)

    assert first.assignments is not None
    assert first.assignments == second.assignments
    assert first.status == second.status
    assert first.shortages == second.shortages


def test_deterministic_repair_returns_the_same_repair():
    scenario = generate_restaurant_scenario(25, seed=42)
    original = _generate(scenario, deterministic=True)

    shift_id, employee_id = pick_callout(original.assignments, seed=1)
    shift = next(s for s in scenario.shifts if s.id == shift_id)
    employees = apply_callout(scenario.employees, employee_id, shift)

    repairs = [
        engine.repair(
            employees=employees,
            shifts=list(scenario.shifts),
            policy=scenario.policy,
            original_schedule=original.assignments,
            deterministic=True,
        )
        for _ in range(2)
    ]

    assert repairs[0].status == repairs[1].status
    assert repairs[0].assignments == repairs[1].assignments


def test_deterministic_and_default_find_equally_good_schedules():
    """Both modes reach the same proven coverage; only the pick may differ."""
    scenario = generate_restaurant_scenario(25, seed=42)

    default = _generate(scenario, deterministic=False)
    repeatable = _generate(scenario, deterministic=True)

    assert default.status == repeatable.status == "OPTIMAL"
    assert sum(s.missing for s in default.shortages) == sum(
        s.missing for s in repeatable.shortages
    )
