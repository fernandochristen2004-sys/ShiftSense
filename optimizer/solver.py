from ortools.sat.python import cp_model
from optimizer.models import Employee, ScheduleResult, SchedulingPolicy, DateTimeShift, FixedAssignment
from optimizer.repair import validate_original_schedule
from optimizer.input_validator import validate_scheduling_inputs
from optimizer.timeutils import (
    datetime_shifts_overlap,
    datetime_shifts_violate_minimum_rest,
    shift_duration_minutes,
    employee_is_available,
)
from datetime import timezone, tzinfo

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
) -> bool:
    """Check minimum rest between datetime shifts."""
    return datetime_shifts_violate_minimum_rest(
        first,
        second,
        minimum_rest_hours * 60,
    )

def generate_schedule(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    original_schedule: dict[int, list[int]] | None = None,
    policy: SchedulingPolicy | None = None,
    scheduling_timezone: tzinfo = timezone.utc,
    outside_assignments: tuple[FixedAssignment, ...] = (),
):
        
    # Validate the complete scheduling dataset.
    validate_scheduling_inputs(
        employees,
        shifts,
        outside_assignments,
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
    for shift in shifts:
        for requirement in shift.requirements:
            model.add(
                sum(
                    role_assignments[
                        (employee.id, shift.id, requirement.skill)
                    ]
                    for employee in employees
                    if (
                        employee.id,
                        shift.id,
                        requirement.skill,
                    ) in role_assignments
                ) == requirement.count
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
                and datetime_shifts_violate_minimum_rest(
                    outside.shift,
                    shift,
                    policy.minimum_rest_hours * 60,
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

    # Find the highest and lowest assigned working minutes.
    max_possible_minutes = sum(
        get_shift_duration_minutes(shift)
        for shift in shifts
    )

    maximum_minutes = model.new_int_var(
        0, max_possible_minutes, "maximum_assigned_minutes"
    )

    minimum_minutes = model.new_int_var(
        0, max_possible_minutes, "minimum_assigned_minutes"
    )

    model.add_max_equality(
        maximum_minutes,
        list(employee_minutes.values())
    )

    model.add_min_equality(
        minimum_minutes,
        list(employee_minutes.values())
    )

    # Select the optimization objective.
    if original_schedule is None:
        # Only optimize fairness when enabled.
        if policy.fairness_enabled:
            model.minimize(maximum_minutes - minimum_minutes)

    
    else:
        # Repair: minimize changes to the original schedule.
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
                    # Removing the employee or changing their role
                    # each costs one change.
                    original_assignment = role_assignments.get(
                        (employee.id, shift.id, original_role)
                    )

                    if original_assignment is None:
                        # The original role is no longer eligible.
                        assignment_changes.append(1)
                    else:
                        assignment_changes.append(
                            1 - original_assignment
                        )

        # Minimize disruption, with optional fairness as a tie-breaker.
        total_changes = sum(assignment_changes)

        if policy.fairness_enabled:
            fairness_gap = maximum_minutes - minimum_minutes
            disruption_weight = max_possible_minutes + 1

            model.minimize(
                disruption_weight * total_changes
                + fairness_gap
            )
        else:
            model.minimize(total_changes)

    # Create the solver and search for a valid schedule.
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    status_name = solver.status_name(status)

    # Return the generated schedule without printing.
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
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
                    and solver.value(
                        role_assignments[
                            (employee.id, shift.id, skill)
                        ]
                    ) == 1
                ]

        return ScheduleResult(
            status=status_name,
            assignments=schedule,
        )

    return ScheduleResult(
        status=status_name,
        assignments=None,
    )

