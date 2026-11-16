from ortools.sat.python import cp_model
from optimizer.models import Employee, ScheduleResult, SchedulingPolicy, DateTimeShift
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
):
        
    # Validate the complete scheduling dataset.
    validate_scheduling_inputs(employees, shifts)

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

    # Store assignment decision variables.
    assignments = {}

    for employee in employees:
        for shift in shifts:
            assignments[(employee.id, shift.id)] = model.new_bool_var(
                f"employee_{employee.id}_shift_{shift.id}"
            )

    # Prevent employees from working shifts they are not qualified for.
    for employee in employees:
        for shift in shifts:
            if shift.required_skill not in employee.skills:
                model.add(
                    assignments[(employee.id, shift.id)] == 0
                )

    # Prevent assignments outside employee availability.
    for employee in employees:
        for shift in shifts:
            available_during_shift = employee_is_available(
                employee,
                shift,
                scheduling_timezone,
            )

            if not available_during_shift:
                model.add(
                    assignments[(employee.id, shift.id)] == 0
                )

    # Add staffing coverage constraints.
    for shift in shifts:
        model.add(
            sum(
                assignments[(employee.id, shift.id)]
                for employee in employees
            ) == shift.required_staff
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

                originally_assigned = (
                    employee.id in original_schedule[shift.id]
                )

                if originally_assigned:
                    # Removing an existing assignment counts as one change.
                    assignment_changes.append(1 - assignment)
                else:
                    # Adding a new assignment counts as one change.
                    assignment_changes.append(assignment)

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
            schedule[shift.id] = [
                employee.id
                for employee in employees
                if solver.value(
                    assignments[(employee.id, shift.id)]
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

