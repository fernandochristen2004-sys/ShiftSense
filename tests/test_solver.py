from optimizer.models import Employee, Shift
from optimizer.sample_data import employees, shifts
from optimizer.solver import generate_schedule


def test_staffing_coverage():
    result = generate_schedule(employees, shifts)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None

    schedule = result.assignments

    # Check that every shift has the required number of employees.
    for shift in shifts:
        assigned_employees = schedule[shift.id]

        assert len(assigned_employees) == shift.required_staff

def test_employee_qualifications():
    result = generate_schedule(employees, shifts)
    
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None
    
    schedule = result.assignments

    # Check the qualifications of every assigned employee.
    for shift in shifts:
        assigned_employee_ids = schedule[shift.id]

        for employee_id in assigned_employee_ids:
            employee = next(
                employee
                for employee in employees
                if employee.id == employee_id
            )

            assert shift.required_skill in employee.skills

def test_no_overlapping_shifts():
    result = generate_schedule(employees, shifts)
    
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None
    
    schedule = result.assignments

    # Check every pair of shifts for each employee.
    for employee in employees:
        for first_index, first_shift in enumerate(shifts):
            for second_shift in shifts[first_index + 1:]:

                # Check whether the employee works both shifts.
                works_first = employee.id in schedule[first_shift.id]
                works_second = employee.id in schedule[second_shift.id]

                # Check whether the shifts overlap.
                same_day = first_shift.day == second_shift.day

                overlaps = (
                    first_shift.start_hour < second_shift.end_hour
                    and second_shift.start_hour < first_shift.end_hour
                )

                # An employee cannot work both overlapping shifts.
                if same_day and overlaps:
                    assert not (works_first and works_second)

def test_maximum_working_hours():
    result = generate_schedule(employees, shifts)
    
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None
    
    schedule = result.assignments

    # Calculate the total assigned hours for each employee.
    for employee in employees:
        total_hours = 0

        for shift in shifts:
            if employee.id in schedule[shift.id]:
                shift_duration = shift.end_hour - shift.start_hour
                total_hours += shift_duration

        # Employees must not exceed their maximum working hours.
        assert total_hours <= employee.max_hours

def test_actual_overlapping_shifts():
    # Create one employee qualified for both shifts.
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
        )
    ]

    # Create two overlapping shifts.
    test_shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        ),
        Shift(
            id=2,
            day=0,
            start_hour=12,
            end_hour=16,
            required_staff=1,
            required_skill="server",
        ),
    ]

    result = generate_schedule(test_employees, test_shifts)

    assert result.status == "INFEASIBLE"
    assert result.assignments is None

def test_insufficient_qualified_staff():
    # Create two employees with different qualifications.
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
        ),
        Employee(
            id=2,
            name="Bob",
            skills=frozenset({"cashier"}),
            max_hours=16,
        ),
    ]

    # This shift requires two servers.
    test_shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=9,
            end_hour=13,
            required_staff=2,
            required_skill="server",
        ),
    ]

    result = generate_schedule(test_employees, test_shifts)

    assert result.status == "INFEASIBLE"
    assert result.assignments is None