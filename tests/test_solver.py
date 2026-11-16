from optimizer.models import Employee, SchedulingPolicy, DateTimeShift, ShiftRequirement, WeeklyAvailability, AvailabilityException, FixedAssignment
from optimizer.sample_data import employees, shifts
from optimizer.solver import generate_schedule, get_shift_duration_minutes
from optimizer.solver import shifts_overlap, shifts_violate_rest
from optimizer.validator import validate_schedule
from datetime import datetime, timedelta, timezone, date, time

def make_shift(
    shift_id: int,
    day: int,
    start_hour: int,
    end_hour: int,
    required_staff: int,
    required_skill: str,
) -> DateTimeShift:
    """Create a datetime shift for solver tests."""

    base_date = datetime(2026, 11, 23, tzinfo=timezone.utc)

    return DateTimeShift(
        id=shift_id,
        starts_at=base_date + timedelta(days=day, hours=start_hour),
        ends_at=base_date + timedelta(days=day, hours=end_hour),
        requirements=(ShiftRequirement(required_skill, required_staff),),
    )


def available_interval(start_day: int, start_hour: int,
                       end_day: int, end_hour: int):
    """Concrete UTC availability interval for migration tests."""
    base = datetime(2026, 11, 23, tzinfo=timezone.utc)
    return (
        base + timedelta(days=start_day, hours=start_hour),
        base + timedelta(days=end_day, hours=end_hour),
    )


def test_staffing_coverage():
    result = generate_schedule(employees, shifts)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None

    schedule = result.assignments

    # Check that every shift has the required number of employees.
    for shift in shifts:
        for requirement in shift.requirements:
            assigned_employees = schedule[shift.id][requirement.skill]
            assert len(assigned_employees) == requirement.count

def test_employee_qualifications():
    result = generate_schedule(employees, shifts)
    
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None
    
    schedule = result.assignments

    # Check the qualifications of every assigned employee.
    for shift in shifts:
        for requirement in shift.requirements:
            assigned_employee_ids = schedule[shift.id][requirement.skill]

            for employee_id in assigned_employee_ids:
                employee = next(
                    employee
                    for employee in employees
                    if employee.id == employee_id
                )

                assert requirement.skill in employee.skills

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
                works_first = any(employee.id in ids for ids in schedule[first_shift.id].values())
                works_second = any(employee.id in ids for ids in schedule[second_shift.id].values())

                overlaps = (
                    first_shift.starts_at < second_shift.ends_at
                    and second_shift.starts_at < first_shift.ends_at
                )

                # An employee cannot work both overlapping shifts.
                if overlaps:
                    assert not (works_first and works_second)

def test_maximum_working_hours():
    result = generate_schedule(employees, shifts)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None

    for employee in employees:
        total_minutes = sum(
            int((shift.ends_at - shift.starts_at).total_seconds() // 60)
            for shift in shifts
            if any(employee.id in ids for ids in result.assignments[shift.id].values())
        )
        assert total_minutes <= employee.max_hours * 60


def test_actual_overlapping_shifts():
    test_employees = [Employee(
        id=1, name="Alice", skills=frozenset({"server"}), max_hours=16,
        datetime_availability=(available_interval(0, 9, 0, 16),),
    )]
    test_shifts = [
        make_shift(1, 0, 9, 13, 1, "server"),
        make_shift(2, 0, 12, 16, 1, "server"),
    ]
    result = generate_schedule(test_employees, test_shifts)
    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_insufficient_qualified_staff():
    test_employees = [
        Employee(id=1, name="Alice", skills=frozenset({"server"}),
                 max_hours=16,
                 datetime_availability=(available_interval(0, 9, 0, 13),)),
        Employee(id=2, name="Bob", skills=frozenset({"cashier"}),
                 max_hours=16,
                 datetime_availability=(available_interval(0, 9, 0, 13),)),
    ]
    test_shifts = [make_shift(1, 0, 9, 13, 2, "server")]
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
            (shift.ends_at - shift.starts_at).total_seconds() / 3600
            for shift in shifts
            if any(employee.id in ids for ids in schedule[shift.id].values())
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
    # Alice can only work Monday; Bob can work Monday or Tuesday.
    test_employees = [
        Employee(id=1, name="Alice", skills=frozenset({"server"}),
                 max_hours=16,
                 datetime_availability=(available_interval(0, 9, 0, 13),)),
        Employee(id=2, name="Bob", skills=frozenset({"server"}),
                 max_hours=16,
                 datetime_availability=(available_interval(0, 9, 1, 13),)),
    ]
    test_shifts = [
        make_shift(1, 0, 9, 13, 1, "server"),
        make_shift(2, 1, 9, 13, 1, "server"),
    ]
    result = generate_schedule(test_employees, test_shifts)
    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert 1 not in result.assignments[2]["server"]
    assert result.assignments[2] == {"server": [2]}


def test_unavailability_causes_infeasibility():
    test_employees = [Employee(
        id=1, name="Alice", skills=frozenset({"server"}), max_hours=16,
        datetime_availability=(available_interval(0, 9, 0, 13),),
    )]
    test_shifts = [make_shift(1, 1, 9, 13, 1, "server")]
    result = generate_schedule(test_employees, test_shifts)
    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_shift_within_available_hours():
    test_employees = [Employee(
        id=1, name="Alice", skills=frozenset({"server"}), max_hours=16,
        datetime_availability=(available_interval(0, 9, 0, 13),),
    )]
    test_shifts = [make_shift(1, 0, 10, 12, 1, "server")]
    result = generate_schedule(test_employees, test_shifts)
    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [1]}}


def test_shift_partially_outside_availability():
    test_employees = [Employee(
        id=1, name="Alice", skills=frozenset({"server"}), max_hours=16,
        datetime_availability=(available_interval(0, 9, 0, 13),),
    )]
    test_shifts = [make_shift(1, 0, 12, 15, 1, "server")]
    result = generate_schedule(test_employees, test_shifts)
    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_shift_without_matching_availability():
    test_employees = [Employee(
        id=1, name="Alice", skills=frozenset({"server"}), max_hours=16,
        datetime_availability=(available_interval(0, 9, 0, 13),),
    )]
    test_shifts = [make_shift(1, 1, 9, 13, 1, "server")]
    result = generate_schedule(test_employees, test_shifts)
    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_generate_schedule_with_no_shifts():
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
        )
    ]

    result = generate_schedule(test_employees, [])

    assert result.status == "OPTIMAL"
    assert result.assignments == {}

def test_solver_accepts_custom_policy():
    test_employees = [Employee(
        id=1, name="Alice", skills=frozenset({"server"}), max_hours=16,
        datetime_availability=(available_interval(0, 9, 0, 13),),
    )]
    test_shifts = [make_shift(1, 0, 9, 13, 1, "server")]
    policy = SchedulingPolicy(
        minimum_rest_hours=11, enforce_minimum_rest=True,
        fairness_enabled=True,
    )
    result = generate_schedule(test_employees, test_shifts, policy=policy)
    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [1]}}


def test_minimum_rest_violation():
    evening_shift = make_shift(1, 0, 17, 23, 1, "server")
    morning_shift = make_shift(2, 1, 7, 11, 1, "server")
    assert shifts_violate_rest(evening_shift, morning_shift, 11) is True
    assert shifts_violate_rest(evening_shift, morning_shift, 8) is False


def test_solver_enforces_minimum_rest():
    test_employees = [Employee(
        id=1, name="Alice", skills=frozenset({"server"}), max_hours=16,
        datetime_availability=(available_interval(0, 17, 1, 11),),
    )]
    test_shifts = [
        make_shift(1, 0, 17, 23, 1, "server"),
        make_shift(2, 1, 7, 11, 1, "server"),
    ]
    policy = SchedulingPolicy(minimum_rest_hours=11,
                              enforce_minimum_rest=True)
    result = generate_schedule(test_employees, test_shifts, policy=policy)
    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_solver_allows_sufficient_rest():
    test_employees = [Employee(
        id=1, name="Alice", skills=frozenset({"server"}), max_hours=16,
        datetime_availability=(available_interval(0, 17, 1, 14),),
    )]
    test_shifts = [
        make_shift(1, 0, 17, 23, 1, "server"),
        make_shift(2, 1, 10, 14, 1, "server"),
    ]
    policy = SchedulingPolicy(minimum_rest_hours=11,
                              enforce_minimum_rest=True)
    result = generate_schedule(test_employees, test_shifts, policy=policy)
    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [1]}, 2: {"server": [1]}}


def test_solver_with_fairness_disabled():
    test_employees = [
        Employee(id=1, name="Alice", skills=frozenset({"server"}),
                 max_hours=16,
                 datetime_availability=(available_interval(0, 9, 0, 13),)),
        Employee(id=2, name="Bob", skills=frozenset({"server"}),
                 max_hours=16,
                 datetime_availability=(available_interval(0, 9, 0, 13),)),
    ]
    test_shifts = [make_shift(1, 0, 9, 13, 1, "server")]
    policy = SchedulingPolicy(fairness_enabled=False)
    result = generate_schedule(test_employees, test_shifts, policy=policy)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None
    assert len(result.assignments[1]["server"]) == 1


def test_get_shift_duration_minutes():
    shift = DateTimeShift(
        id=100,
        starts_at=datetime(
            2026, 11, 21, 20, 30,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 2, 15,
            tzinfo=timezone.utc,
        ),
        requirements=(ShiftRequirement("server", 1),),
    )

    assert get_shift_duration_minutes(shift) == 345

def test_solver_datetime_shifts_overlap():
    first = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 21, 20, 0,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 2, 0,
            tzinfo=timezone.utc,
        ),
        requirements=(ShiftRequirement("server", 1),),
    )

    second = DateTimeShift(
        id=2,
        starts_at=datetime(
            2026, 11, 22, 1, 0,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 5, 0,
            tzinfo=timezone.utc,
        ),
        requirements=(ShiftRequirement("server", 1),),
    )

    assert shifts_overlap(first, second)

def test_solver_datetime_minimum_rest_helper():
    first = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 21, 20, 0,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 2, 0,
            tzinfo=timezone.utc,
        ),
        requirements=(ShiftRequirement("server", 1),),
    )

    second = DateTimeShift(
        id=2,
        starts_at=datetime(
            2026, 11, 22, 7, 0,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 11, 0,
            tzinfo=timezone.utc,
        ),
        requirements=(ShiftRequirement("server", 1),),
    )

    assert shifts_violate_rest(first, second, 11)

def test_solver_generates_datetime_schedule():
    start = datetime(
        2026, 11, 21, 20, 30,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2026, 11, 22, 2, 15,
        tzinfo=timezone.utc,
    )

    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=((start, end),),
        )
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=start,
            ends_at=end,
            requirements=(ShiftRequirement("server", 1),),
        )
    ]

    result = generate_schedule(employees, shifts)

    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [1]}}

def test_solver_rejects_datetime_minimum_rest_violation():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(
                (
                    datetime(2026, 11, 21, 17, 0, tzinfo=timezone.utc),
                    datetime(2026, 11, 22, 14, 0, tzinfo=timezone.utc),
                ),
            ),
        )
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=datetime(2026, 11, 21, 17, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 11, 21, 23, 0, tzinfo=timezone.utc),
            requirements=(ShiftRequirement("server", 1),),
        ),
        DateTimeShift(
            id=2,
            starts_at=datetime(2026, 11, 22, 7, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 11, 22, 11, 0, tzinfo=timezone.utc),
            requirements=(ShiftRequirement("server", 1),),
        ),
    ]

    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    result = generate_schedule(
        employees,
        shifts,
        policy=policy,
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None

def test_solver_allows_exact_datetime_minimum_rest():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(
                (
                    datetime(2026, 11, 21, 17, 0, tzinfo=timezone.utc),
                    datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc),
                ),
            ),
        )
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=datetime(
                2026, 11, 21, 17, 0, tzinfo=timezone.utc
            ),
            ends_at=datetime(
                2026, 11, 21, 23, 0, tzinfo=timezone.utc
            ),
            requirements=(ShiftRequirement("server", 1),),
        ),
        DateTimeShift(
            id=2,
            starts_at=datetime(
                2026, 11, 22, 10, 0, tzinfo=timezone.utc
            ),
            ends_at=datetime(
                2026, 11, 22, 14, 0, tzinfo=timezone.utc
            ),
            requirements=(ShiftRequirement("server", 1),),
        ),
    ]

    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    result = generate_schedule(
        employees,
        shifts,
        policy=policy,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"server": [1]},
        2: {"server": [1]},
    }

def test_datetime_schedule_passes_independent_validator():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(
                (
                    datetime(
                        2026, 11, 21, 18, 0,
                        tzinfo=timezone.utc,
                    ),
                    datetime(
                        2026, 11, 22, 17, 0,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
        )
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=datetime(
                2026, 11, 21, 20, 0,
                tzinfo=timezone.utc,
            ),
            ends_at=datetime(
                2026, 11, 22, 2, 0,
                tzinfo=timezone.utc,
            ),
            requirements=(ShiftRequirement("server", 1),),
        ),
        DateTimeShift(
            id=2,
            starts_at=datetime(
                2026, 11, 22, 13, 0,
                tzinfo=timezone.utc,
            ),
            ends_at=datetime(
                2026, 11, 22, 17, 0,
                tzinfo=timezone.utc,
            ),
            requirements=(ShiftRequirement("server", 1),),
        ),
    ]

    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    result = generate_schedule(
        employees,
        shifts,
        policy=policy,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    errors = validate_schedule(
        employees,
        shifts,
        result.assignments,
        policy=policy,
    )

    assert errors == []

def test_solver_respects_weekly_availability():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9, 0), time(17, 0)),
        ),
    )

    monday_shift = make_shift(1, 0, 9, 13, 1, "server")
    tuesday_shift = make_shift(2, 1, 9, 13, 1, "server")

    monday_result = generate_schedule(
        [employee], [monday_shift]
    )

    tuesday_result = generate_schedule(
        [employee], [tuesday_shift]
    )

    assert monday_result.status == "OPTIMAL"
    assert monday_result.assignments == {1: {"server": [1]}}

    assert tuesday_result.status == "INFEASIBLE"
    assert tuesday_result.assignments is None


def test_solver_respects_day_off_exception():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9, 0), time(17, 0)),
        ),
        availability_exceptions=(
            AvailabilityException(
                date(2026, 11, 30),
                False,
            ),
        ),
    )

    shift = make_shift(1, 7, 9, 13, 1, "server")

    result = generate_schedule([employee], [shift])

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_solver_respects_exception_working_hours():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9, 0), time(17, 0)),
        ),
        availability_exceptions=(
            AvailabilityException(
                date(2026, 11, 30),
                True,
                ((time(13, 0), time(17, 0)),),
            ),
        ),
    )

    morning_shift = make_shift(1, 7, 9, 13, 1, "server")
    afternoon_shift = make_shift(2, 7, 13, 17, 1, "server")

    morning_result = generate_schedule(
        [employee], [morning_shift]
    )

    afternoon_result = generate_schedule(
        [employee], [afternoon_shift]
    )

    assert morning_result.status == "INFEASIBLE"
    assert morning_result.assignments is None

    assert afternoon_result.status == "OPTIMAL"
    assert afternoon_result.assignments == {2: {"server": [1]}}

def test_solver_respects_scheduling_timezone():
    malaysia_timezone = timezone(timedelta(hours=8))

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9), time(17)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 30, 1, tzinfo=timezone.utc
        ),
        ends_at=datetime(
            2026, 11, 30, 5, tzinfo=timezone.utc
        ),
        requirements=(ShiftRequirement("server", 1),),
    )

    result = generate_schedule(
        [employee],
        [shift],
        scheduling_timezone=malaysia_timezone,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [1]}}


def test_solver_rejects_shift_outside_local_availability():
    malaysia_timezone = timezone(timedelta(hours=8))

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9), time(17)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 30, 9, tzinfo=timezone.utc
        ),
        ends_at=datetime(
            2026, 11, 30, 13, tzinfo=timezone.utc
        ),
        requirements=(ShiftRequirement("server", 1),),
    )

    result = generate_schedule(
        [employee],
        [shift],
        scheduling_timezone=malaysia_timezone,
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_outside_assignment_blocks_insufficient_rest():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        datetime_availability=(
            available_interval(0, 7, 0, 11),
        ),
    )

    outside = (
        FixedAssignment(
            employee_id=1,
            shift=make_shift(100, -1, 15, 23, 1, "server"),
        ),
    )

    monday_shift = make_shift(1, 0, 7, 11, 1, "server")

    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    result = generate_schedule(
        [employee],
        [monday_shift],
        policy=policy,
        outside_assignments=outside,
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_outside_assignment_allows_exact_minimum_rest():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        datetime_availability=(
            available_interval(0, 10, 0, 14),
        ),
    )

    outside = (
        FixedAssignment(
            employee_id=1,
            shift=make_shift(100, -1, 15, 23, 1, "server"),
        ),
    )

    monday_shift = make_shift(1, 0, 10, 14, 1, "server")

    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    result = generate_schedule(
        [employee],
        [monday_shift],
        policy=policy,
        outside_assignments=outside,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {1: {"server": [1]}}


def test_future_outside_assignment_blocks_late_shift():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        datetime_availability=(
            available_interval(6, 17, 6, 23),
        ),
    )

    outside = (
        FixedAssignment(
            employee_id=1,
            shift=make_shift(100, 7, 7, 11, 1, "server"),
        ),
    )

    sunday_shift = make_shift(1, 6, 17, 23, 1, "server")

    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    result = generate_schedule(
        [employee],
        [sunday_shift],
        policy=policy,
        outside_assignments=outside,
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_outside_assignment_blocks_overlap_without_rest_policy():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        datetime_availability=(
            available_interval(0, 9, 0, 17),
        ),
    )

    outside = (
        FixedAssignment(
            employee_id=1,
            shift=make_shift(100, 0, 10, 14, 1, "server"),
        ),
    )

    planning_shift = make_shift(1, 0, 9, 13, 1, "server")

    result = generate_schedule(
        [employee],
        [planning_shift],
        outside_assignments=outside,
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None
