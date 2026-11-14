from optimizer.models import Employee, Shift


def count_assignment_changes(
    original_schedule: dict[int, list[int]],
    repaired_schedule: dict[int, list[int]],
) -> int:
    """
    Count employee-shift assignments added or removed
    between two schedules.
    """
    changes = 0

    for shift_id in original_schedule:
        original_employees = set(original_schedule[shift_id])
        repaired_employees = set(repaired_schedule[shift_id])

        removed = original_employees - repaired_employees
        added = repaired_employees - original_employees

        changes += len(removed) + len(added)

    return changes

def validate_original_schedule(
    original_schedule: dict[int, list[int]],
    employees: list[Employee],
    shifts: list[Shift],
) -> None:
    """
    Validate the structure and references of an original schedule.

    Raises ValueError when the schedule contains invalid data.
    """
    valid_employee_ids = {employee.id for employee in employees}
    valid_shift_ids = {shift.id for shift in shifts}

    if set(original_schedule) != valid_shift_ids:
        raise ValueError(
            "Original schedule must contain exactly the expected shift IDs."
        )

    for shift_id, assigned_employee_ids in original_schedule.items():
        if len(assigned_employee_ids) != len(set(assigned_employee_ids)):
            raise ValueError(
                f"Shift {shift_id} contains duplicate employee assignments."
            )

        for employee_id in assigned_employee_ids:
            if employee_id not in valid_employee_ids:
                raise ValueError(
                    f"Shift {shift_id} references unknown employee "
                    f"{employee_id}."
                )