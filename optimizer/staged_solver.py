
from dataclasses import dataclass
from time import monotonic

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class OptimizationStage:
    """One objective in lexicographic priority order."""

    name: str
    expression: object


@dataclass(frozen=True)
class StagedSolveResult:
    """Solver outcome and the best retained solution."""

    status: str
    variable_values: dict[int, int] | None
    objective_values: dict[str, int]
    stage_statuses: dict[str, str]


def solve_stages(
    model: cp_model.CpModel,
    stages: list[OptimizationStage],
    tracked_variables: list,
    time_limit_seconds: float = 10.0,
    first_stage_fraction: float = 0.5,
) -> StagedSolveResult:
    """
    Optimize objectives in priority order using one CP-SAT model.

    Earlier stages receive larger time allocations. A successful
    stage constrains its objective before the next stage begins.
    """

    if time_limit_seconds <= 0:
        raise ValueError("Time limit must be positive.")

    if not stages:
        raise ValueError(
            "At least one optimization stage is required."
        )

    if not 0 < first_stage_fraction <= 1:
        raise ValueError(
            "First-stage fraction must be greater than 0 "
            "and at most 1."
        )

    if len(stages) > 1 and first_stage_fraction == 1:
        raise ValueError(
            "First-stage fraction must be less than 1 "
            "when multiple stages are present."
        )

    deadline = monotonic() + time_limit_seconds

    stage_statuses = {}
    best_values = None
    last_successful_solver = None
    all_stages_optimal = True
    last_status = "UNKNOWN"

    for stage_index, stage in enumerate(stages):
        remaining = deadline - monotonic()

        if remaining <= 0:
            all_stages_optimal = False
            break

        stages_left = len(stages) - stage_index

        # Reserve time for later stages when possible.
        if stages_left == 1:
            stage_budget = remaining
        elif stage_index == 0:
            stage_budget = remaining * first_stage_fraction
        else:
            stage_budget = remaining / stages_left

        model.minimize(stage.expression)

        # Seed this stage using the previous valid solution.
        if best_values is not None:
            model.clear_hints()

            for variable in tracked_variables:
                model.add_hint(
                    variable,
                    best_values[variable.index],
                )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = stage_budget

        status = solver.solve(model)
        last_status = solver.status_name(status)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            all_stages_optimal = False
            break

        stage_statuses[stage.name] = last_status

        if status != cp_model.OPTIMAL:
            all_stages_optimal = False

        best_values = {
            variable.index: solver.value(variable)
            for variable in tracked_variables
        }

        last_successful_solver = solver

        achieved_value = int(
            solver.value(stage.expression)
        )

        # Preserve this stage's achieved value.
        if stage_index < len(stages) - 1:
            model.add(
                stage.expression <= achieved_value
            )

    if best_values is None:
        return StagedSolveResult(
            status=last_status,
            variable_values=None,
            objective_values={},
            stage_statuses=stage_statuses,
        )

    # All reported metrics describe the retained solution.
    objective_values = {
        stage.name: int(
            last_successful_solver.value(stage.expression)
        )
        for stage in stages
        if stage.name in stage_statuses
    }

    final_status = (
        "OPTIMAL"
        if all_stages_optimal
        and len(stage_statuses) == len(stages)
        else "FEASIBLE"
    )

    return StagedSolveResult(
        status=final_status,
        variable_values=best_values,
        objective_values=objective_values,
        stage_statuses=stage_statuses,
    )
