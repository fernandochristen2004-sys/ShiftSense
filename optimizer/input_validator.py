from optimizer.models import Employee, DateTimeShift, FixedAssignment


def validate_scheduling_inputs(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    outside_assignments: tuple[FixedAssignment, ...] = (),
    locked_assignments: dict[int, dict[str, list[int]]] | None = None,
    excluded_assignments: dict[int, list[int]] | None = None,
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

    # Validate locked assignments within the planning window.
    if locked_assignments is None:
        locked_assignments = {}

    if not isinstance(locked_assignments, dict):
        raise ValueError(
            "Locked assignments must be a dictionary."
        )

    shift_by_id = {
        shift.id: shift
        for shift in shifts
    }

    for shift_id, role_assignments in locked_assignments.items():
        if shift_id not in shift_by_id:
            raise ValueError(
                f"Locked assignment references unknown shift {shift_id}."
            )

        if not isinstance(role_assignments, dict):
            raise ValueError(
                f"Locked assignments for shift {shift_id} "
                "must be a dictionary."
            )

        shift = shift_by_id[shift_id]

        requirement_counts = {
            requirement.skill: requirement.count
            for requirement in shift.requirements
        }

        seen_employees = set()

        for skill, assigned_ids in role_assignments.items():
            if skill not in requirement_counts:
                raise ValueError(
                    f"Shift {shift_id} has an unknown locked role "
                    f"'{skill}'."
                )

            if not isinstance(assigned_ids, list):
                raise ValueError(
                    f"Shift {shift_id}, role {skill}: "
                    "locked assignments must be a list."
                )

            if len(assigned_ids) > requirement_counts[skill]:
                raise ValueError(
                    f"Shift {shift_id}, role {skill}: "
                    "locked assignments exceed staffing requirements."
                )

            for employee_id in assigned_ids:
                if employee_id not in known_employee_ids:
                    raise ValueError(
                        f"Shift {shift_id}: locked assignment "
                        f"references unknown employee {employee_id}."
                    )

                if employee_id in seen_employees:
                    raise ValueError(
                        f"Shift {shift_id}: duplicate locked "
                        "employee assignment."
                    )

                seen_employees.add(employee_id)


    # Validate excluded assignments within the planning window.
    if excluded_assignments is None:
        excluded_assignments = {}

    if not isinstance(excluded_assignments, dict):
        raise ValueError(
            "Excluded assignments must be a dictionary."
        )

    # Collect positive locks to detect contradictions.
    positive_locks = set()

    for shift_id, role_assignments in locked_assignments.items():
        for assigned_ids in role_assignments.values():
            for employee_id in assigned_ids:
                positive_locks.add((employee_id, shift_id))

    for shift_id, excluded_ids in excluded_assignments.items():
        if shift_id not in shift_by_id:
            raise ValueError(
                f"Excluded assignment references unknown shift {shift_id}."
            )

        if not isinstance(excluded_ids, list):
            raise ValueError(
                f"Excluded assignments for shift {shift_id} "
                "must be a list."
            )

        seen_exclusions = set()

        for employee_id in excluded_ids:
            if employee_id not in known_employee_ids:
                raise ValueError(
                    f"Shift {shift_id}: excluded assignment "
                    f"references unknown employee {employee_id}."
                )

            if employee_id in seen_exclusions:
                raise ValueError(
                    f"Shift {shift_id}: duplicate excluded "
                    "employee assignment."
                )

            if (employee_id, shift_id) in positive_locks:
                raise ValueError(
                    f"Shift {shift_id}: employee {employee_id} "
                    "cannot be both locked and excluded."
                )

            seen_exclusions.add(employee_id)
