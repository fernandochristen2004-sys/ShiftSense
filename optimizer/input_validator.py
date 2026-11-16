from optimizer.models import Employee, DateTimeShift


def validate_scheduling_inputs(
    employees: list[Employee],
    shifts: list[DateTimeShift],
) -> None:
    """
    Validate scheduling data before optimization.

    Raises ValueError when the dataset is invalid.
    """

    # Check for duplicate employee IDs.
    employee_ids = [employee.id for employee in employees]

    if len(employee_ids) != len(set(employee_ids)):
        raise ValueError("Duplicate employee IDs detected.")

    # Check for duplicate shift IDs.
    shift_ids = [shift.id for shift in shifts]

    if len(shift_ids) != len(set(shift_ids)):
        raise ValueError("Duplicate shift IDs detected.")

    # Only datetime-based shifts are supported.
    if any(
        not isinstance(shift, DateTimeShift)
        for shift in shifts
    ):
        raise ValueError(
            "All shifts must use the DateTimeShift model."
        )

    # A scheduling problem must contain at least one employee.
    if not employees:
        raise ValueError(
            "At least one employee is required."
        )