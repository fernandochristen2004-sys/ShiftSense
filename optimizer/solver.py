from ortools.sat.python import cp_model
from optimizer.models import Employee, ScheduleResult, SchedulingPolicy, DateTimeShift, FixedAssignment
from optimizer.repair import validate_original_schedule, count_assignment_changes
from optimizer.input_validator import validate_scheduling_inputs
from optimizer.timeutils import (
    datetime_shifts_overlap,
    datetime_shifts_violate_minimum_rest,
    shift_duration_minutes,
    employee_is_available,
    datetime_shifts_violate_rest_policy,
)
from datetime import timezone, tzinfo
from optimizer.lock_conflicts import find_lock_conflicts
from optimizer.staged_solver import OptimizationStage, solve_stages
from optimizer.schedule_metrics import calculate_schedule_metrics
from optimizer.coverage_metrics import calculate_coverage

def get_shift_duration_minutes(
    shift: DateTimeShift,
) -> int:
    """Calculate duration for a datetime shift."""
    return shift_duration_minutes(shift)

def shifts_overlap(
    first: DateTimeShift,
    second: DateTimeShift,
) -> bool:
    """Check whether two shifts overlap."""
    return datetime_shifts_overlap(first, second)

def shifts_violate_rest(
    first: DateTimeShift,
    second: DateTimeShift,
    minimum_rest_hours: int,
    allow_split_shifts: bool = False,
    split_shift_min_break_minutes: int = 120,
    max_split_span_minutes: int = 780,
) -> bool:
    """Check the configured rest and split-shift rules."""
    return datetime_shifts_violate_rest_policy(
        first,
        second,
        minimum_rest_hours * 60,
        allow_split_shifts,
        split_shift_min_break_minutes,
        max_split_span_minutes,
    )

def generate_schedule(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    original_schedule: dict[int, dict[str, list[int]]] | None = None,
    policy: SchedulingPolicy | None = None,
    scheduling_timezone: tzinfo = timezone.utc,
    outside_assignments: tuple[FixedAssignment, ...] = (),
    locked_assignments: dict[int, dict[str, list[int]]] | None = None,
    excluded_assignments: dict[int, list[int]] | None = None,
):


    # Validate the complete scheduling dataset.
    validate_scheduling_inputs(
        employees,
        shifts,
        outside_assignments,
        locked_assignments,
        excluded_assignments,
    )

    # Validate the original schedule before attempting repair.
    if original_schedule is not None:
        validate_original_schedule(
            original_schedule,
            employees,
            shifts,
        )

    # No optimization is needed when there are no shifts.
    if not shifts:
        return ScheduleResult(
            status="OPTIMAL",
            assignments={},
            objective_values={},
            stage_statuses={"feasibility": "OPTIMAL"},
            schedule_metrics=calculate_schedule_metrics(
                employees,
                shifts,
                {},
            ),
            fully_covered=True,
            shortages=(),
        )

    # Use the default scheduling policy if none is provided.
    if policy is None:
        policy = SchedulingPolicy()

    # Create the constraint programming model.
    model = cp_model.CpModel()

    # Store role-specific and employee-shift decision variables.
    role_assignments = {}
    assignments = {}

    for employee in employees:
        for shift in shifts:
            assignment = model.new_bool_var(
                f"employee_{employee.id}_shift_{shift.id}"
            )
            assignments[(employee.id, shift.id)] = assignment

            available = employee_is_available(
                employee,
                shift,
                scheduling_timezone,
            )

            eligible_roles = []

            for requirement in shift.requirements:
                if (
                    requirement.skill in employee.skills
                    and available
                ):
                    role_assignment = model.new_bool_var(
                        f"employee_{employee.id}_shift_{shift.id}"
                        f"_role_{requirement.skill}"
                    )

                    role_assignments[
                        (employee.id, shift.id, requirement.skill)
                    ] = role_assignment

                    eligible_roles.append(role_assignment)

            # An employee can fill at most one role per shift.
            model.add(sum(eligible_roles) <= 1)

            # Working the shift means filling exactly one role.
            model.add(assignment == sum(eligible_roles))

    
    # Add staffing coverage constraints for each required role.
    shortage_variables = {}

    for shift in shifts:
        for requirement in shift.requirements:
            assigned_count = sum(
                role_assignments[
                    (employee.id, shift.id, requirement.skill)
                ]
                for employee in employees
                if (
                    employee.id,
                    shift.id,
                    requirement.skill,
                ) in role_assignments
            )

            if not policy.allow_partial_coverage:
                # Preserve the original exact-staffing behavior.
                model.add(assigned_count == requirement.count)
                continue

            # The minimum remains a hard requirement.
            model.add(
                assigned_count >= requirement.effective_min_count
            )

            # Never schedule more employees than the target.
            model.add(assigned_count <= requirement.count)

            # Record how many target positions remain unfilled.
            shortage = model.new_int_var(
                0,
                requirement.count - requirement.effective_min_count,
                f"shortage_shift_{shift.id}_role_{requirement.skill}",
            )

            model.add(
                shortage == requirement.count - assigned_count
            )

            shortage_variables[
                (shift.id, requirement.skill)
            ] = shortage


    # Enforce locked employee assignments within the planning window.
    if locked_assignments is not None:
        for shift_id, role_locks in locked_assignments.items():
            for skill, employee_ids in role_locks.items():
                for employee_id in employee_ids:
                    role_assignment = role_assignments.get(
                        (employee_id, shift_id, skill)
                    )

                    if role_assignment is None:
                        # The employee is unavailable or unqualified.
                        # A valid lock must not be silently ignored.
                        model.add(0 == 1)
                    else:
                        # Keep the employee in this exact shift and role.
                        model.add(role_assignment == 1)


    # Prevent excluded employees from working specified shifts.
    if excluded_assignments is not None:
        for shift_id, employee_ids in excluded_assignments.items():
            for employee_id in employee_ids:
                model.add(
                    assignments[(employee_id, shift_id)] == 0
                )


    # Prevent employees from working overlapping shifts.
    for employee in employees:
        for first_index, first_shift in enumerate(shifts):
            for second_shift in shifts[first_index + 1:]:

                if shifts_overlap(first_shift, second_shift):
                    model.add(
                        assignments[(employee.id, first_shift.id)]
                        + assignments[(employee.id, second_shift.id)]
                        <= 1
                    )

    # Enforce the configured minimum rest between shifts.
    if policy.enforce_minimum_rest:
        for employee in employees:
            for first_index, first_shift in enumerate(shifts):
                for second_shift in shifts[first_index + 1:]:

                    violates_rest = shifts_violate_rest(
                        first_shift,
                        second_shift,
                        policy.minimum_rest_hours,
                        policy.allow_split_shifts,
                        policy.split_shift_min_break_minutes,
                        policy.max_split_span_minutes,
                    )

                    if violates_rest:
                        model.add(
                            assignments[(employee.id, first_shift.id)]
                            + assignments[(employee.id, second_shift.id)]
                            <= 1
                        )

    # Respect fixed assignments outside the planning window.
    for outside in outside_assignments:
        for shift in shifts:
            # Outside assignments are facts, not decision variables.
            assignment = assignments[
                (outside.employee_id, shift.id)
            ]

            # An employee cannot work overlapping shifts.
            if datetime_shifts_overlap(outside.shift, shift):
                model.add(assignment == 0)
                continue

            # Enforce minimum rest against fixed outside shifts.
            if (
                policy.enforce_minimum_rest
                and datetime_shifts_violate_rest_policy(
                    outside.shift,
                    shift,
                    policy.minimum_rest_hours * 60,
                    policy.allow_split_shifts,
                    policy.split_shift_min_break_minutes,
                    policy.max_split_span_minutes,
                )
            ):
                model.add(assignment == 0)

    # Ensure employees do not exceed their maximum working hours.
    for employee in employees:
        model.add(
            sum(
                get_shift_duration_minutes(shift)
                * assignments[(employee.id, shift.id)]
                for shift in shifts
            ) <= employee.max_hours * 60
        )

    # Calculate the total assigned minutes for each employee.
    employee_minutes = {}

    for employee in employees:
        employee_minutes[employee.id] = sum(
            get_shift_duration_minutes(shift)
            * assignments[(employee.id, shift.id)]
            for shift in shifts
        )


    # Calculate the total available shift minutes.
    # Used to bound target-deviation and fairness variables.
    max_possible_minutes = sum(
        get_shift_duration_minutes(shift)
        for shift in shifts
    )


    # Build fairness objectives for employees with target hours.
    target_deviations = []
    untargeted_minutes = []

    for employee in employees:
        assigned_minutes = employee_minutes[employee.id]

        if employee.target_minutes is None:
            untargeted_minutes.append(assigned_minutes)
            continue

        # Deviation is the absolute difference between assigned
        # working minutes and the employee's preferred target.
        deviation_limit = max(
            max_possible_minutes,
            employee.target_minutes,
        )

        deviation = model.new_int_var(
            0,
            deviation_limit,
            f"target_deviation_employee_{employee.id}",
        )

        model.add_abs_equality(
            deviation,
            assigned_minutes - employee.target_minutes,
        )

        target_deviations.append(deviation)

    # Total deviation across employees with explicit targets.
    total_target_deviation = None
    maximum_target_deviation = None

    if target_deviations:
        total_deviation_limit = sum(
            max(
                max_possible_minutes,
                employee.target_minutes,
            )
            for employee in employees
            if employee.target_minutes is not None
        )

        total_target_deviation = model.new_int_var(
            0,
            total_deviation_limit,
            "total_target_deviation",
        )

        model.add(
            total_target_deviation == sum(target_deviations)
        )

        maximum_target_deviation = model.new_int_var(
            0,
            total_deviation_limit,
            "maximum_target_deviation",
        )

        model.add_max_equality(
            maximum_target_deviation,
            target_deviations,
        )

    # Balance workloads only among employees without targets.
    untargeted_gap = None

    if len(untargeted_minutes) >= 2:
        untargeted_maximum = model.new_int_var(
            0,
            max_possible_minutes,
            "untargeted_maximum_minutes",
        )

        untargeted_minimum = model.new_int_var(
            0,
            max_possible_minutes,
            "untargeted_minimum_minutes",
        )

        model.add_max_equality(
            untargeted_maximum,
            untargeted_minutes,
        )

        model.add_min_equality(
            untargeted_minimum,
            untargeted_minutes,
        )

        untargeted_gap = model.new_int_var(
            0,
            max_possible_minutes,
            "untargeted_workload_gap",
        )

        model.add(
            untargeted_gap
            == untargeted_maximum - untargeted_minimum
        )

    
    # Build optimization stages in strict priority order.
    stages = []

    # Coverage always takes priority over repair and fairness.
    if policy.allow_partial_coverage and shortage_variables:
        total_shortage = sum(shortage_variables.values())

        stages.append(
            OptimizationStage(
                "coverage_shortage",
                total_shortage,
            )
        )

    if original_schedule is not None:
        # Repair: minimize disruption after staffing coverage.
        assignment_changes = []

        for employee in employees:
            for shift in shifts:
                assignment = assignments[(employee.id, shift.id)]

                original_role = next(
                    (
                        skill
                        for skill, employee_ids
                        in original_schedule[shift.id].items()
                        if employee.id in employee_ids
                    ),
                    None,
                )

                if original_role is None:
                    # Adding an employee costs one change.
                    assignment_changes.append(assignment)
                else:
                    # Removing or changing role costs one change.
                    original_assignment = role_assignments.get(
                        (employee.id, shift.id, original_role)
                    )

                    if original_assignment is None:
                        assignment_changes.append(1)
                    else:
                        assignment_changes.append(
                            1 - original_assignment
                        )

        total_changes = sum(assignment_changes)

        stages.append(
            OptimizationStage(
                "disruption",
                total_changes,
            )
        )

    # Add fairness objectives only when enabled.
    if policy.fairness_enabled:
        if total_target_deviation is not None:
            stages.append(
                OptimizationStage(
                    "target_deviation_min",
                    total_target_deviation,
                )
            )

            stages.append(
                OptimizationStage(
                    "max_deviation_min",
                    maximum_target_deviation,
                )
            )

        if untargeted_gap is not None:
            stages.append(
                OptimizationStage(
                    "untargeted_gap_min",
                    untargeted_gap,
                )
            )


    # Solve using staged optimization when objectives exist.
    objective_values = {}
    stage_statuses = {}

    if stages:
        # Track role assignments for schedule reconstruction.
        tracked_variables = list(role_assignments.values())

        staged_result = solve_stages(
            model=model,
            stages=stages,
            tracked_variables=tracked_variables,
            time_limit_seconds=10.0,
        )

        status_name = staged_result.status
        solution_values = staged_result.variable_values
        objective_values = staged_result.objective_values
        stage_statuses = staged_result.stage_statuses

    else:
        # Feasibility-only mode: no optimization objective.
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0

        status = solver.solve(model)
        status_name = solver.status_name(status)

        solution_values = None

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solution_values = {
                variable.index: solver.value(variable)
                for variable in role_assignments.values()
            }

        stage_statuses = {
            "feasibility": status_name,
        }

    # Return the best retained schedule without printing.
    if solution_values is not None:
        schedule = {}

        for shift in shifts:
            schedule[shift.id] = {}

            for requirement in shift.requirements:
                skill = requirement.skill

                schedule[shift.id][skill] = [
                    employee.id
                    for employee in employees
                    if (
                        employee.id,
                        shift.id,
                        skill,
                    ) in role_assignments
                    and solution_values[
                        role_assignments[
                            (employee.id, shift.id, skill)
                        ].index
                    ] == 1
                ]

        # Calculate coverage from the generated schedule.
        fully_covered, shortages = calculate_coverage(
            shifts,
            schedule,
        )

        # Measure actual disruption independently of the solver.
        actual_changes = None

        if original_schedule is not None:
            actual_changes = count_assignment_changes(
                original_schedule,
                schedule,
            )

        return ScheduleResult(
            status=status_name,
            assignments=schedule,
            objective_values=objective_values,
            stage_statuses=stage_statuses,
            schedule_metrics=calculate_schedule_metrics(
                employees,
                shifts,
                schedule,
            ),
            fully_covered=fully_covered,
            shortages=shortages,
            assignment_changes=actual_changes,
        )

    # Explain direct lock conflicts only when infeasibility
    # has actually been proven.
    conflicts = ()

    if status_name == "INFEASIBLE":
        conflicts = find_lock_conflicts(
            employees=employees,
            shifts=shifts,
            locked_assignments=locked_assignments,
            policy=policy,
            scheduling_timezone=scheduling_timezone,
            outside_assignments=outside_assignments,
        )

    return ScheduleResult(
        status=status_name,
        assignments=None,
        conflicts=conflicts,
        objective_values=objective_values,
        stage_statuses=stage_statuses,
    )
