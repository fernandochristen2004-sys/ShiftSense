from optimizer.models import Employee, Shift, SchedulingPolicy
from optimizer.timeutils import shifts_violate_minimum_rest

def validate_schedule(
    employees: list[Employee],
    shifts: list[Shift],
    schedule: dict[int, list[int]],
    policy: SchedulingPolicy | None = None,
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

    # Check staffing coverage and employee references.
    for shift in shifts:
        assigned_ids = schedule.get(shift.id, [])

        if len(assigned_ids) != shift.required_staff:
            errors.append(
                f"Shift {shift.id}: expected "
                f"{shift.required_staff} employees, "
                f"found {len(assigned_ids)}."
            )

        if len(assigned_ids) != len(set(assigned_ids)):
            errors.append(
                f"Shift {shift.id}: duplicate employee assignments."
            )

        # Check employee references and qualifications.
        for employee_id in assigned_ids:
            if employee_id not in employee_by_id:
                errors.append(
                    f"Shift {shift.id}: unknown employee {employee_id}."
                )
                continue

            employee = employee_by_id[employee_id]

            if shift.required_skill not in employee.skills:
                errors.append(
                    f"Shift {shift.id}: employee {employee_id} "
                    f"does not have the required skill "
                    f"'{shift.required_skill}'."
                )

            # Check whether the employee is available on this day.
            available_on_day = shift.day in employee.available_days

            # Check whether the entire shift fits an available interval.
            available_during_shift = (
                employee.availability is None
                or any(
                    interval.day == shift.day
                    and interval.start_hour <= shift.start_hour
                    and interval.end_hour >= shift.end_hour
                    for interval in employee.availability
                )
            )

            if not (available_on_day and available_during_shift):
                errors.append(
                    f"Shift {shift.id}: employee {employee_id} "
                    "is unavailable during the assigned shift."
                )

    # Check whether employees have overlapping assignments.
    for employee in employees:
        for first_index, first_shift in enumerate(shifts):
            for second_shift in shifts[first_index + 1:]:

                # Check whether the employee works both shifts.
                works_first = (
                    employee.id in schedule.get(first_shift.id, [])
                )

                works_second = (
                    employee.id in schedule.get(second_shift.id, [])
                )

                if not (works_first and works_second):
                    continue

                # Check whether the shifts overlap.
                same_day = first_shift.day == second_shift.day

                overlaps = (
                    first_shift.start_hour < second_shift.end_hour
                    and second_shift.start_hour < first_shift.end_hour
                )

                if same_day and overlaps:
                    errors.append(
                        f"Employee {employee.id} has overlapping "
                        f"shifts {first_shift.id} and {second_shift.id}."
                    )    

    # Check whether employees exceed their maximum working hours.
    for employee in employees:
        total_hours = 0

        for shift in shifts:
            if employee.id in schedule.get(shift.id, []):
                shift_duration = shift.end_hour - shift.start_hour
                total_hours += shift_duration

        if total_hours > employee.max_hours:
            errors.append(
                f"Employee {employee.id} exceeds maximum working hours: "
                f"{total_hours} assigned, "
                f"{employee.max_hours} allowed."
            )

    # Check minimum rest between assigned shifts.
    if policy.enforce_minimum_rest:
        for employee in employees:
            for first_index, first_shift in enumerate(shifts):
                for second_shift in shifts[first_index + 1:]:

                    works_first = (
                        employee.id in schedule.get(first_shift.id, [])
                    )

                    works_second = (
                        employee.id in schedule.get(second_shift.id, [])
                    )

                    if not (works_first and works_second):
                        continue

                    if shifts_violate_minimum_rest(
                        first_shift,
                        second_shift,
                        policy.minimum_rest_hours,
                    ):
                        errors.append(
                            f"Employee {employee.id} violates minimum "
                            f"rest between shifts {first_shift.id} "
                            f"and {second_shift.id}."
                        )

    return errors