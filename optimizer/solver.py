from ortools.sat.python import cp_model
from optimizer.models import Employee, Shift, ScheduleResult


def generate_schedule(
    employees: list[Employee],
    shifts: list[Shift],
):
    
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

            # Check whether the employee is available on this day.
            available_on_day = shift.day in employee.available_days

            # Check whether the shift fits an available time interval.
            available_during_shift = (
                employee.availability is None
                or any(
                    interval.day == shift.day
                    and interval.start_hour <= shift.start_hour
                    and interval.end_hour >= shift.end_hour
                    for interval in employee.availability
                )
            )

            # Both availability conditions must be satisfied.
            if not (available_on_day and available_during_shift):
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

                same_day = first_shift.day == second_shift.day

                overlaps = (
                    first_shift.start_hour < second_shift.end_hour
                    and second_shift.start_hour < first_shift.end_hour
                )

                if same_day and overlaps:
                    model.add(
                        assignments[(employee.id, first_shift.id)]
                        + assignments[(employee.id, second_shift.id)]
                        <= 1
                    )

    # Ensure employees do not exceed their maximum working hours.
    for employee in employees:
        model.add(
            sum(
                (shift.end_hour - shift.start_hour)
                * assignments[(employee.id, shift.id)]
                for shift in shifts
            ) <= employee.max_hours
        )

    # Calculate the total assigned hours for each employee.
    employee_hours = {}

    for employee in employees:
        employee_hours[employee.id] = sum(
            (shift.end_hour - shift.start_hour)
            * assignments[(employee.id, shift.id)]
            for shift in shifts
        )

    # Find the highest and lowest assigned working hours.
    max_possible_hours = sum(
        shift.end_hour - shift.start_hour
        for shift in shifts
    )

    maximum_hours = model.new_int_var(
        0, max_possible_hours, "maximum_assigned_hours"
    )

    minimum_hours = model.new_int_var(
        0, max_possible_hours, "minimum_assigned_hours"
    )

    model.add_max_equality(
        maximum_hours,
        list(employee_hours.values())
    )

    model.add_min_equality(
        minimum_hours,
        list(employee_hours.values())
    )

    # Minimize the difference between maximum and minimum hours.
    model.minimize(maximum_hours - minimum_hours)

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

