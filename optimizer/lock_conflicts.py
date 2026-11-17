from datetime import timezone, tzinfo
from optimizer.models import (
    DateTimeShift,
    Employee,
    FixedAssignment,
    SchedulingPolicy,
)
from optimizer.timeutils import (
    datetime_shifts_overlap,
    datetime_shifts_violate_rest_policy,
    employee_is_available,
    shift_duration_minutes,
)


def find_lock_conflicts(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    locked_assignments: dict[int, dict[str, list[int]]] | None,
    policy: SchedulingPolicy,
    scheduling_timezone: tzinfo = timezone.utc,
    outside_assignments: tuple[FixedAssignment, ...] = (),
) -> tuple[str, ...]:
    """Identify direct conflicts involving required assignments."""

    if not locked_assignments:
        return ()

    employee_by_id = {
        employee.id: employee
        for employee in employees
    }

    shift_by_id = {
        shift.id: shift
        for shift in shifts
    }

    conflicts = []
    locked_shifts_by_employee = {}

    # Check each required employee-shift-role assignment.
    for shift_id, role_locks in locked_assignments.items():
        shift = shift_by_id[shift_id]

        for skill, employee_ids in role_locks.items():
            for employee_id in employee_ids:
                employee = employee_by_id[employee_id]

                locked_shifts_by_employee.setdefault(
                    employee_id, []
                ).append(shift)

                if skill not in employee.skills:
                    conflicts.append(
                        f"Employee {employee_id} is locked as "
                        f"{skill} on Shift {shift_id} but lacks "
                        f"the required skill '{skill}'."
                    )

                if not employee_is_available(
                    employee,
                    shift,
                    scheduling_timezone,
                ):
                    conflicts.append(
                        f"Employee {employee_id} is locked to "
                        f"Shift {shift_id} but is unavailable "
                        "during that shift."
                    )

    # Check conflicts between locked shifts.
    for employee_id, employee_shifts in (
        locked_shifts_by_employee.items()
    ):
        employee = employee_by_id[employee_id]

        total_minutes = sum(
            shift_duration_minutes(shift)
            for shift in employee_shifts
        )

        if total_minutes > employee.max_hours * 60:
            conflicts.append(
                f"Employee {employee_id} has "
                f"{total_minutes} locked working minutes, "
                f"exceeding their maximum of "
                f"{employee.max_hours * 60} minutes."
            )

        for index, first_shift in enumerate(employee_shifts):
            for second_shift in employee_shifts[index + 1:]:
                if datetime_shifts_overlap(
                    first_shift,
                    second_shift,
                ):
                    conflicts.append(
                        f"Employee {employee_id} is locked "
                        f"to overlapping shifts "
                        f"{first_shift.id} and {second_shift.id}."
                    )
                    continue

                if (
                    policy.enforce_minimum_rest
                    and datetime_shifts_violate_rest_policy(
                        first_shift,
                        second_shift,
                        policy.minimum_rest_hours * 60,
                        policy.allow_split_shifts,
                        policy.split_shift_min_break_minutes,
                        policy.max_split_span_minutes,
                    )
                ):
                    conflicts.append(
                        f"Employee {employee_id} is locked "
                        f"to shifts {first_shift.id} and "
                        f"{second_shift.id}, violating the "
                        f"required {policy.minimum_rest_hours}"
                        "-hour minimum rest period."
                    )

        # Check locked shifts against outside commitments.
        for shift in employee_shifts:
            for outside in outside_assignments:
                if outside.employee_id != employee_id:
                    continue

                if datetime_shifts_overlap(
                    shift,
                    outside.shift,
                ):
                    conflicts.append(
                        f"Employee {employee_id} is locked "
                        f"to Shift {shift.id}, which overlaps "
                        f"outside Shift {outside.shift.id}."
                    )
                    continue

                if (
                    policy.enforce_minimum_rest
                    and datetime_shifts_violate_rest_policy(
                        shift,
                        outside.shift,
                        policy.minimum_rest_hours * 60,
                        policy.allow_split_shifts,
                        policy.split_shift_min_break_minutes,
                        policy.max_split_span_minutes,
                    )
                ):
                    conflicts.append(
                        f"Employee {employee_id} is locked "
                        f"to Shift {shift.id}, violating "
                        f"minimum rest against outside "
                        f"Shift {outside.shift.id} "
                        f"({policy.minimum_rest_hours} "
                        "hours required)."
                    )

    return tuple(conflicts)
