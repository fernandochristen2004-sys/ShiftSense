from optimizer.models import Employee, SchedulingPolicy, DateTimeShift, FixedAssignment
from optimizer.timeutils import (
    datetime_shifts_overlap,
    datetime_shifts_violate_minimum_rest,
    employee_is_available,
    shift_duration_minutes,
)
from datetime import timezone, tzinfo


def validate_schedule(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    schedule: dict[int, dict[str, list[int]]],
    policy: SchedulingPolicy | None = None,
    scheduling_timezone: tzinfo = timezone.utc,
    outside_assignments: tuple[FixedAssignment, ...] = (),
) -> list[str]:
    """
    Validate a generated schedule.

    Returns a list of validation errors.
    An empty list means no violations were detected.
    """

    # Use the default policy if none is provided.
    if policy is None:
        policy = SchedulingPolicy()

    errors = []

    employee_by_id = {
        employee.id: employee
        for employee in employees
    }

    # Check that the schedule contains exactly the expected shifts.
    expected_shift_ids = {shift.id for shift in shifts}

    if set(schedule) != expected_shift_ids:
        errors.append("Schedule contains missing or unexpected shifts.")

    # Track employees working each shift, regardless of role.
    assigned_by_shift = {}

    # Check staffing coverage and employee references.
    for shift in shifts:
        role_assignments = schedule.get(shift.id, {})

        expected_roles = {
            requirement.skill
            for requirement in shift.requirements
        }

        if not isinstance(role_assignments, dict):
            errors.append(
                f"Shift {shift.id}: role assignments must be a dictionary."
            )
            assigned_by_shift[shift.id] = set()
            continue

        if set(role_assignments) != expected_roles:
            errors.append(
                f"Shift {shift.id}: missing or unexpected roles."
            )

        all_assigned_ids = []

        for requirement in shift.requirements:
            skill = requirement.skill
            assigned_ids = role_assignments.get(skill, [])

            if not isinstance(assigned_ids, list):
                errors.append(
                    f"Shift {shift.id}, role {skill}: "
                    "assignments must be a list."
                )
                continue

            if len(assigned_ids) != requirement.count:
                errors.append(
                    f"Shift {shift.id}, role {skill}: expected "
                    f"{requirement.count} employees, "
                    f"found {len(assigned_ids)}."
                )

            all_assigned_ids.extend(assigned_ids)

            # Check employee references and qualifications.
            for employee_id in assigned_ids:
                if employee_id not in employee_by_id:
                    errors.append(
                        f"Shift {shift.id}: unknown employee {employee_id}."
                    )
                    continue

                employee = employee_by_id[employee_id]

                if skill not in employee.skills:
                    errors.append(
                        f"Shift {shift.id}: employee {employee_id} "
                        f"does not have the required skill '{skill}'."
                    )

                # Check employee availability.
                available = employee_is_available(
                    employee,
                    shift,
                    scheduling_timezone,
                )

                if not available:
                    errors.append(
                        f"Shift {shift.id}: employee {employee_id} "
                        "is unavailable during the assigned shift."
                    )

        if len(all_assigned_ids) != len(set(all_assigned_ids)):
            errors.append(
                f"Shift {shift.id}: duplicate employee assignments."
            )

        assigned_by_shift[shift.id] = set(all_assigned_ids)

    # Check whether employees have overlapping assignments.
    for employee in employees:
        for first_index, first_shift in enumerate(shifts):
            for second_shift in shifts[first_index + 1:]:

                # Check whether the employee works both shifts.
                works_first = (
                    employee.id in assigned_by_shift.get(
                        first_shift.id, set()
                    )
                )

                works_second = (
                    employee.id in assigned_by_shift.get(
                        second_shift.id, set()
                    )
                )

                if not (works_first and works_second):
                    continue

                # Check whether the shifts overlap.
                overlaps = datetime_shifts_overlap(
                    first_shift,
                    second_shift,
                )

                if overlaps:
                    errors.append(
                        f"Employee {employee.id} has overlapping "
                        f"shifts {first_shift.id} and {second_shift.id}."
                    )

    # Check whether employees exceed their maximum working hours.
    for employee in employees:
        total_minutes = 0

        for shift in shifts:
            if employee.id in assigned_by_shift.get(shift.id, set()):
                shift_duration = shift_duration_minutes(shift)
                total_minutes += shift_duration

        if total_minutes > employee.max_hours * 60:
            errors.append(
                f"Employee {employee.id} exceeds maximum working hours: "
                f"{total_minutes} minutes assigned, "
                f"{employee.max_hours * 60} minutes allowed."
            )

    # Check minimum rest between assigned shifts.
    if policy.enforce_minimum_rest:
        for employee in employees:
            for first_index, first_shift in enumerate(shifts):
                for second_shift in shifts[first_index + 1:]:

                    works_first = (
                        employee.id in assigned_by_shift.get(
                            first_shift.id, set()
                        )
                    )

                    works_second = (
                        employee.id in assigned_by_shift.get(
                            second_shift.id, set()
                        )
                    )

                    if not (works_first and works_second):
                        continue

                    # Check minimum rest using the correct time model.
                    violates_rest = (
                        datetime_shifts_violate_minimum_rest(
                            first_shift,
                            second_shift,
                            policy.minimum_rest_hours * 60,
                        )
                    )

                    if violates_rest:
                        errors.append(
                            f"Employee {employee.id} violates minimum "
                            f"rest between shifts {first_shift.id} "
                            f"and {second_shift.id}."
                        )

    # Check assignments against fixed outside commitments.
    for outside in outside_assignments:
        for shift in shifts:
            if outside.employee_id not in assigned_by_shift.get(
                shift.id, set()
            ):
                continue

            if datetime_shifts_overlap(outside.shift, shift):
                errors.append(
                    f"Employee {outside.employee_id} has an overlapping "
                    f"outside assignment for shift {shift.id}."
                )
                continue

            if (
                policy.enforce_minimum_rest
                and datetime_shifts_violate_minimum_rest(
                    outside.shift,
                    shift,
                    policy.minimum_rest_hours * 60,
                )
            ):
                errors.append(
                    f"Employee {outside.employee_id} violates minimum "
                    f"rest against an outside assignment "
                    f"for shift {shift.id}."
                )

    return errors