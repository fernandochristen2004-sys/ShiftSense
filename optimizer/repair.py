from optimizer.models import Employee, DateTimeShift


def count_assignment_changes(
    original_schedule: dict[int, dict[str, list[int]]],
    repaired_schedule: dict[int, dict[str, list[int]]],
) -> int:
    """
    Count assignment changes between role-aware schedules.

    A role change on the same shift costs one.
    Removing or adding an employee costs one each.
    """
    changes = 0

    for shift_id in original_schedule:
        original_roles = original_schedule[shift_id]
        repaired_roles = repaired_schedule[shift_id]

        original_assignments = {
            employee_id: skill
            for skill, employee_ids in original_roles.items()
            for employee_id in employee_ids
        }

        repaired_assignments = {
            employee_id: skill
            for skill, employee_ids in repaired_roles.items()
            for employee_id in employee_ids
        }

        for employee_id in (
            original_assignments.keys()
            | repaired_assignments.keys()
        ):
            original_role = original_assignments.get(employee_id)
            repaired_role = repaired_assignments.get(employee_id)

            if original_role != repaired_role:
                changes += 1

    return changes


def validate_original_schedule(
    original_schedule: dict[int, dict[str, list[int]]],
    employees: list[Employee],
    shifts: list[DateTimeShift],
) -> None:
    """
    Validate the structure and references of an original schedule.

    Raises ValueError when the schedule contains invalid data.
    """
    valid_employee_ids = {employee.id for employee in employees}
    shift_by_id = {shift.id: shift for shift in shifts}

    if set(original_schedule) != set(shift_by_id):
        raise ValueError(
            "Original schedule must contain exactly the expected shift IDs."
        )

    for shift_id, role_assignments in original_schedule.items():
        if not isinstance(role_assignments, dict):
            raise ValueError(
                f"Shift {shift_id} must contain role assignments."
            )

        expected_roles = {
            requirement.skill
            for requirement in shift_by_id[shift_id].requirements
        }

        if set(role_assignments) != expected_roles:
            raise ValueError(
                f"Shift {shift_id} must contain exactly "
                "the expected roles."
            )

        seen_employees = set()

        for skill, employee_ids in role_assignments.items():
            if not isinstance(employee_ids, list):
                raise ValueError(
                    f"Shift {shift_id}, role {skill} must contain "
                    "a list of employee IDs."
                )

            for employee_id in employee_ids:
                if employee_id not in valid_employee_ids:
                    raise ValueError(
                        f"Shift {shift_id} references unknown employee "
                        f"{employee_id}."
                    )

                if employee_id in seen_employees:
                    raise ValueError(
                        f"Shift {shift_id} contains duplicate "
                        "employee assignments."
                    )

                seen_employees.add(employee_id)
