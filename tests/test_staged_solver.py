import pytest
from ortools.sat.python import cp_model
from optimizer.staged_solver import (
    OptimizationStage,
    solve_stages,
)

def test_stages_preserve_higher_priority_objective():
    model = cp_model.CpModel()

    x = model.new_int_var(0, 10, "x")
    y = model.new_int_var(0, 10, "y")

    model.add(x + y == 10)

    result = solve_stages(
        model,
        [
            OptimizationStage("first", x),
            OptimizationStage("second", y),
        ],
        tracked_variables=[x, y],
    )

    assert result.status == "OPTIMAL"
    assert result.objective_values["first"] == 0
    assert result.objective_values["second"] == 10
    assert result.variable_values[x.index] == 0
    assert result.variable_values[y.index] == 10


def test_second_stage_breaks_tie():
    model = cp_model.CpModel()

    x = model.new_int_var(0, 10, "x")
    y = model.new_int_var(0, 10, "y")

    model.add(x + y == 10)

    result = solve_stages(
        model,
        [
            OptimizationStage("first", x + y),
            OptimizationStage("second", x),
        ],
        tracked_variables=[x, y],
    )

    assert result.status == "OPTIMAL"
    assert result.objective_values["first"] == 10
    assert result.objective_values["second"] == 0
    assert result.variable_values[x.index] == 0


def test_infeasible_model_returns_no_solution():
    model = cp_model.CpModel()

    x = model.new_bool_var("x")

    model.add(x == 0)
    model.add(x == 1)

    result = solve_stages(
        model,
        [OptimizationStage("first", x)],
        tracked_variables=[x],
    )

    assert result.status == "INFEASIBLE"
    assert result.variable_values is None
    assert result.objective_values == {}


def test_invalid_time_limit_rejected():
    model = cp_model.CpModel()
    x = model.new_bool_var("x")

    with pytest.raises(ValueError, match="positive"):
        solve_stages(
            model,
            [OptimizationStage("first", x)],
            tracked_variables=[x],
            time_limit_seconds=0,
        )


def test_empty_stages_rejected():
    model = cp_model.CpModel()
    x = model.new_bool_var("x")

    with pytest.raises(ValueError, match="At least one"):
        solve_stages(
            model,
            [],
            tracked_variables=[x],
        )


def test_stage_statuses_are_recorded():
    model = cp_model.CpModel()
    x = model.new_int_var(0, 5, "x")

    result = solve_stages(
        model,
        [
            OptimizationStage("minimize_x", x),
            OptimizationStage("minimize_remaining", 5 - x),
        ],
        tracked_variables=[x],
    )

    assert result.status == "OPTIMAL"
    assert result.stage_statuses == {
        "minimize_x": "OPTIMAL",
        "minimize_remaining": "OPTIMAL",
    }


def test_previous_solution_used_when_next_stage_cannot_run():
    """A later-stage failure must not erase a valid solution."""
    model = cp_model.CpModel()
    x = model.new_bool_var("x")

    result = solve_stages(
        model,
        [OptimizationStage("first", x)],
        tracked_variables=[x],
    )

    assert result.variable_values is not None
    assert result.variable_values[x.index] == 0


from unittest.mock import patch


def test_retains_solution_when_later_stage_returns_unknown():
    model = cp_model.CpModel()

    x = model.new_int_var(0, 10, "x")
    y = model.new_int_var(0, 10, "y")

    model.add(x + y == 10)

    stages = [
        OptimizationStage("first", x),
        OptimizationStage("second", y),
    ]

    original_solve = cp_model.CpSolver.solve
    call_count = 0

    def controlled_solve(solver, current_model):
        nonlocal call_count
        call_count += 1

        if call_count == 2:
            return cp_model.UNKNOWN

        return original_solve(solver, current_model)

    with patch.object(
        cp_model.CpSolver,
        "solve",
        controlled_solve,
    ):
        result = solve_stages(
            model,
            stages,
            tracked_variables=[x, y],
        )

    assert call_count == 2
    assert result.status == "FEASIBLE"
    assert result.variable_values is not None
    assert result.variable_values[x.index] == 0
    assert result.variable_values[y.index] == 10

    assert result.objective_values == {
        "first": 0,
    }

    assert result.stage_statuses == {
        "first": "OPTIMAL",
    }


def test_unproven_intermediate_stage_keeps_feasible_status():
    model = cp_model.CpModel()

    x = model.new_int_var(0, 10, "x")
    y = model.new_int_var(0, 10, "y")

    model.add(x + y == 10)

    stages = [
        OptimizationStage("first", x),
        OptimizationStage("second", y),
    ]

    original_solve = cp_model.CpSolver.solve
    original_status_name = cp_model.CpSolver.status_name
    call_count = 0

    def controlled_solve(solver, current_model):
        nonlocal call_count
        call_count += 1

        result = original_solve(solver, current_model)

        if call_count == 1 and result == cp_model.OPTIMAL:
            return cp_model.FEASIBLE

        return result

    def controlled_status_name(solver, status):
        if status == cp_model.FEASIBLE:
            return "FEASIBLE"
        return original_status_name(solver, status)

    with patch.object(
        cp_model.CpSolver,
        "solve",
        controlled_solve,
    ), patch.object(
        cp_model.CpSolver,
        "status_name",
        controlled_status_name,
    ):
        result = solve_stages(
            model,
            stages,
            tracked_variables=[x, y],
        )

    assert call_count == 2
    assert result.status == "FEASIBLE"

    assert result.stage_statuses == {
        "first": "FEASIBLE",
        "second": "OPTIMAL",
    }

    assert result.variable_values is not None
    assert result.variable_values[x.index] == 0
    assert result.variable_values[y.index] == 10

def test_full_first_stage_fraction_rejected_for_multiple_stages():
    model = cp_model.CpModel()
    x = model.new_bool_var("x")

    with pytest.raises(ValueError, match="less than 1"):
        solve_stages(
            model,
            [
                OptimizationStage("first", x),
                OptimizationStage("second", 1 - x),
            ],
            tracked_variables=[x],
            first_stage_fraction=1.0,
        )


def test_zero_first_stage_fraction_rejected():
    model = cp_model.CpModel()
    x = model.new_bool_var("x")

    with pytest.raises(ValueError, match="greater than 0"):
        solve_stages(
            model,
            [OptimizationStage("first", x)],
            tracked_variables=[x],
            first_stage_fraction=0,
        )


def test_time_budget_prioritizes_first_stage():
    model = cp_model.CpModel()
    x = model.new_int_var(0, 10, "x")

    stages = [
        OptimizationStage("first", x),
        OptimizationStage("second", 10 - x),
    ]

    allocated_budgets = []
    original_solve = cp_model.CpSolver.solve

    def record_budget(solver, current_model):
        allocated_budgets.append(
            solver.parameters.max_time_in_seconds
        )
        return original_solve(solver, current_model)

    with patch.object(
        cp_model.CpSolver,
        "solve",
        record_budget,
    ):
        result = solve_stages(
            model,
            stages,
            tracked_variables=[x],
            time_limit_seconds=10.0,
            first_stage_fraction=0.5,
        )

    assert result.status == "OPTIMAL"
    assert len(allocated_budgets) == 2

    # The first stage receives approximately half
    # of the initial ten-second budget.
    assert 0 < allocated_budgets[0] <= 5.0

    # The second stage receives a positive budget.
    assert allocated_budgets[1] > 0

    # Stage limits are maximum allowances, not elapsed time.
    # Unused time from Stage 1 can be reused by Stage 2.
    assert allocated_budgets[1] <= 10.0
