from optimizer.models import Employee, DateTimeShift, FixedAssignment


def validate_scheduling_inputs(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    outside_assignments: tuple[FixedAssignment, ...] = (),
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

    # Validate fixed assignments outside the planning window.
    if not isinstance(outside_assignments, tuple):
        raise ValueError(
            "Outside assignments must be a tuple."
        )

    known_employee_ids = set(employee_ids)
    planning_shift_ids = set(shift_ids)
    seen_assignments = set()

    for assignment in outside_assignments:
        if not isinstance(assignment, FixedAssignment):
            raise ValueError(
                "Outside assignments must contain "
                "FixedAssignment objects."
            )

        if assignment.employee_id not in known_employee_ids:
            raise ValueError(
                "Outside assignment references an unknown employee."
            )

        if assignment.shift.id in planning_shift_ids:
            raise ValueError(
                "Outside assignment shift ID conflicts "
                "with a planning shift."
            )

        if assignment.shift.id in planning_shift_ids:
            raise ValueError(
                "Outside assignment shift ID conflicts "
                "with a planning shift."
            )

        # Reject duplicate fixed assignments.
        assignment_key = (
            assignment.employee_id,
            assignment.shift.id,
        )

        if assignment_key in seen_assignments:
            raise ValueError(
                "Duplicate outside fixed assignment detected."
            )

        seen_assignments.add(assignment_key)