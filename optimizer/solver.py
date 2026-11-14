from ortools.sat.python import cp_model
from optimizer.models import Employee, Shift, ScheduleResult
from optimizer.sample_data import employees, shifts


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

    # Create the solver and search for a valid schedule.
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    status_name = solver.status_name(status)

    # Check whether a valid schedule was found.
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("Valid schedule generated successfully!")

        # Display employees assigned to each shift.
        for shift in shifts:
            print(
                f"\nDay {shift.day}, "
                f"{shift.start_hour}:00–{shift.end_hour}:00 "
                f"({shift.required_skill})"
            )

            for employee in employees:
                assignment = assignments[(employee.id, shift.id)]

                if solver.value(assignment) == 1:
                    print(f"  - {employee.name}")

        # Store assignments so automated tests can check them.
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
    
    else:
        print(f"Scheduling ended with status: {status_name}")

        return ScheduleResult(
            status=status_name,
            assignments=None,
        )


if __name__ == "__main__":
    generate_schedule(employees, shifts)