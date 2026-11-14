from optimizer.models import Employee, Shift, Availability
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

def test_workload_fairness():
    # Generate an optimized schedule.
    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    schedule = result.assignments

    # Calculate the assigned hours for each employee.
    employee_hours = {}

    for employee in employees:
        total_hours = sum(
            shift.end_hour - shift.start_hour
            for shift in shifts
            if employee.id in schedule[shift.id]
        )

        employee_hours[employee.id] = total_hours

    # Calculate the difference between maximum and minimum hours.
    fairness_gap = (
        max(employee_hours.values())
        - min(employee_hours.values())
    )

    # The optimal fairness gap for our current sample is 4 hours.
    assert fairness_gap == 4

def test_employee_unavailability():
    # Alice is only available on Monday.
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            available_days=frozenset({0}),
        ),
        Employee(
            id=2,
            name="Bob",
            skills=frozenset({"server"}),
            max_hours=16,
            available_days=frozenset({0, 1}),
        ),
    ]

    # One shift on Monday and another on Tuesday.
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
            day=1,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        ),
    ]

    result = generate_schedule(test_employees, test_shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Alice must not be assigned to Tuesday.
    assert 1 not in result.assignments[2]

    # Bob must cover Tuesday because Alice is unavailable.
    assert result.assignments[2] == [2]

def test_unavailability_causes_infeasibility():
    # Alice is only available on Monday.
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            available_days=frozenset({0}),
        )
    ]

    # The shift requires a server on Tuesday.
    test_shifts = [
        Shift(
            id=1,
            day=1,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        )
    ]

    # Attempt to generate a schedule.
    result = generate_schedule(test_employees, test_shifts)

    # The shift cannot be staffed.
    assert result.status == "INFEASIBLE"
    assert result.assignments is None

def test_shift_within_available_hours():
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            availability=(
                Availability(day=0, start_hour=9, end_hour=13),
            ),
        )
    ]

    test_shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=10,
            end_hour=12,
            required_staff=1,
            required_skill="server",
        )
    ]

    result = generate_schedule(test_employees, test_shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments == {1: [1]}

def test_shift_partially_outside_availability():
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            availability=(
                Availability(day=0, start_hour=9, end_hour=13),
            ),
        )
    ]

    test_shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=12,
            end_hour=15,
            required_staff=1,
            required_skill="server",
        )
    ]

    result = generate_schedule(test_employees, test_shifts)

    assert result.status == "INFEASIBLE"
    assert result.assignments is None

def test_shift_without_matching_availability():
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            availability=(
                Availability(day=0, start_hour=9, end_hour=13),
            ),
        )
    ]

    test_shifts = [
        Shift(
            id=1,
            day=1,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        )
    ]

    result = generate_schedule(test_employees, test_shifts)

    assert result.status == "INFEASIBLE"
    assert result.assignments is None