from optimizer.models import Employee, SchedulingPolicy, DateTimeShift, WeeklyAvailability, AvailabilityException
from optimizer.validator import validate_schedule
from optimizer.sample_data import employees, shifts
from optimizer.solver import generate_schedule
from datetime import datetime, timedelta, timezone, date, time
from optimizer.timeutils import shift_fits_interval
from optimizer.input_validator import validate_scheduling_inputs
import pytest


def make_shift(shift_id, day, start_hour, end_hour, required_staff, required_skill):
    """Create a timezone-aware shift anchored to 23 November 2026."""
    base = datetime(2026, 11, 23, tzinfo=timezone.utc)
    return DateTimeShift(
        id=shift_id,
        starts_at=base + timedelta(days=day, hours=start_hour),
        ends_at=base + timedelta(days=day, hours=end_hour),
        required_staff=required_staff,
        required_skill=required_skill,
    )


def available_interval(start_day, start_hour, end_day, end_hour):
    base = datetime(2026, 11, 23, tzinfo=timezone.utc)
    return (
        base + timedelta(days=start_day, hours=start_hour),
        base + timedelta(days=end_day, hours=end_hour),
    )

def test_valid_schedule():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(available_interval(0, 9, 0, 13),),
        )
    ]

    shifts = [
        make_shift(1, 0, 9, 13, 1, "server")
    ]

    schedule = {1: [1]}

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
    )

    assert errors == []

@pytest.mark.parametrize(
    "schedule, expected_error",
    [
        (
            {1: []},
            "expected 1 employees, found 0",
        ),
        (
            {1: [1, 1]},
            "duplicate employee assignments",
        ),
        (
            {1: [99]},
            "unknown employee 99",
        ),
        (
            {2: [1]},
            "missing or unexpected shifts",
        ),
    ],
)
def test_invalid_schedule(schedule, expected_error):
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(available_interval(0, 9, 0, 13),),
        )
    ]

    shifts = [
        make_shift(1, 0, 9, 13, 1, "server")
    ]

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
    )

    assert any(
        expected_error in error
        for error in errors
    )

def test_unqualified_employee():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"cashier"}),
            max_hours=16,
            datetime_availability=(available_interval(0, 9, 0, 13),),
        )
    ]

    shifts = [
        make_shift(1, 0, 9, 13, 1, "server")
    ]

    schedule = {1: [1]}

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
    )

    assert any(
        "does not have the required skill" in error
        for error in errors
    )

def test_employee_outside_availability():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(available_interval(0, 9, 0, 13),),
        )
    ]

    shifts = [
        make_shift(1, 0, 12, 16, 1, "server")
    ]

    schedule = {1: [1]}

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
    )

    assert any(
        "is unavailable during the assigned shift" in error
        for error in errors
    )

def test_employee_overlapping_shifts():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(available_interval(0, 9, 0, 16),),
        )
    ]

    shifts = [
        make_shift(1, 0, 9, 13, 1, "server"),
        make_shift(2, 0, 12, 16, 1, "server"),
    ]

    # Alice is incorrectly assigned to both overlapping shifts.
    schedule = {
        1: [1],
        2: [1],
    }

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
    )

    assert any(
        "overlapping shifts" in error
        for error in errors
    )

def test_employee_exceeds_maximum_hours():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=(available_interval(0, 9, 2, 13),),
        )
    ]

    shifts = [
        make_shift(1, 0, 9, 13, 1, "server"),
        make_shift(2, 1, 9, 13, 1, "server"),
        make_shift(3, 2, 9, 13, 1, "server"),
    ]

    schedule = {
        1: [1],
        2: [1],
        3: [1],
    }

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
    )

    assert any(
        "exceeds maximum working hours" in error
        for error in errors
    )

def test_generated_schedule_passes_validation():
    # Generate a schedule using OR-Tools.
    result = generate_schedule(employees, shifts)

    # Verify that the solver found an optimal schedule.
    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Independently validate the generated assignments.
    errors = validate_schedule(
        employees,
        shifts,
        result.assignments,
    )

    # A correctly generated schedule should have no violations.
    assert errors == []

@pytest.mark.parametrize(
    "employee_data",
    [
        {"id": -1, "name": "Alice", "max_hours": 16},
        {"id": 1, "name": "", "max_hours": 16},
        {"id": 1, "name": "Alice", "max_hours": -5},
        {
            "id": 1,
            "name": "Alice",
            "max_hours": 16,
            "datetime_availability": ((
                datetime(2026, 11, 23, 9, 0),
                datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc),
            ),),
        },
    ],
)
def test_invalid_employee_data(employee_data):
    with pytest.raises(ValueError):
        Employee(
            skills=frozenset({"server"}),
            **employee_data,
        )

@pytest.mark.parametrize(
    "changes",
    [
        {"id": -1},
        {"starts_at": datetime(2026, 11, 23, 9, 0)},
        {"ends_at": datetime(2026, 11, 23, 13, 0)},
        {"ends_at": datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)},
        {"ends_at": datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)},
        {"required_staff": -2},
        {"required_skill": ""},
    ],
)
def test_invalid_shift_data(changes):
    valid_data = {
        "id": 1,
        "starts_at": datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc),
        "ends_at": datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc),
        "required_staff": 1,
        "required_skill": "server",
    }

    valid_data.update(changes)

    with pytest.raises(ValueError):
        DateTimeShift(**valid_data)


@pytest.mark.parametrize(
    "interval",
    [
        (datetime(2026, 11, 23, 9, 0),
         datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)),
        (datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc),
         datetime(2026, 11, 23, 17, 0)),
        available_interval(0, 17, 0, 9),
        available_interval(0, 13, 0, 13),
        (datetime(2026, 11, 23, 9, 0, 30, tzinfo=timezone.utc),
         datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)),
        (datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc),
         datetime(2026, 11, 23, 17, 0, 30, tzinfo=timezone.utc)),
        ("09:00", datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)),
    ],
)
def test_invalid_availability_data(interval):
    with pytest.raises(ValueError):
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(interval,),
        )


def test_validator_detects_minimum_rest_violation():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(available_interval(0, 17, 1, 11),),
        )
    ]

    shifts = [
        make_shift(1, 0, 17, 23, 1, "server"),
        make_shift(2, 1, 7, 11, 1, "server"),
    ]

    schedule = {
        1: [1],
        2: [1],
    }

    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
        policy=policy,
    )

    assert any(
        "violates minimum rest" in error
        for error in errors
    )

def test_datetime_availability_interval():
    shift = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 21, 20, 0,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 2, 0,
            tzinfo=timezone.utc,
        ),
        required_staff=1,
        required_skill="server",
    )

    available_start = datetime(
        2026, 11, 21, 18, 0,
        tzinfo=timezone.utc,
    )

    available_end = datetime(
        2026, 11, 22, 3, 0,
        tzinfo=timezone.utc,
    )

    assert shift_fits_interval(
        shift, available_start, available_end
    )

    unavailable_end = datetime(
        2026, 11, 21, 23, 0,
        tzinfo=timezone.utc,
    )

    assert not shift_fits_interval(
        shift, available_start, unavailable_end
    )

def test_validator_detects_datetime_overlap():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
            datetime_availability=(
                (
                    datetime(2026, 11, 21, 18, 0, tzinfo=timezone.utc),
                    datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc),
                ),
            ),
        )
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 11, 22, 2, 0, tzinfo=timezone.utc),
            required_staff=1,
            required_skill="server",
        ),
        DateTimeShift(
            id=2,
            starts_at=datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 11, 22, 5, 0, tzinfo=timezone.utc),
            required_staff=1,
            required_skill="server",
        ),
    ]

    schedule = {
        1: [1],
        2: [1],
    }

    errors = validate_schedule(employees, shifts, schedule)

    assert any(
        "overlapping" in error
        for error in errors
    )

def test_validator_detects_datetime_minimum_rest_violation():
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
            starts_at=datetime(
                2026, 11, 21, 17, 0, tzinfo=timezone.utc
            ),
            ends_at=datetime(
                2026, 11, 21, 23, 0, tzinfo=timezone.utc
            ),
            required_staff=1,
            required_skill="server",
        ),
        DateTimeShift(
            id=2,
            starts_at=datetime(
                2026, 11, 22, 7, 0, tzinfo=timezone.utc
            ),
            ends_at=datetime(
                2026, 11, 22, 11, 0, tzinfo=timezone.utc
            ),
            required_staff=1,
            required_skill="server",
        ),
    ]

    schedule = {
        1: [1],
        2: [1],
    }

    policy = SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
    )

    errors = validate_schedule(
        employees,
        shifts,
        schedule,
        policy=policy,
    )

    assert any(
        "violates minimum rest" in error
        for error in errors
    )

def test_rejects_unsupported_shift_models():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=20,
        )
    ]

    class UnsupportedShift:
        id = 1

    shifts = [
        UnsupportedShift(),
    ]

    with pytest.raises(
        ValueError,
        match="All shifts must use the DateTimeShift model",
    ):
        validate_scheduling_inputs(employees, shifts)

def test_validator_rejects_weekly_unavailability():
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
        starts_at=datetime(2026, 11, 24, 9, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 24, 13, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    errors = validate_schedule(
        [employee],
        [shift],
        {1: [1]},
    )

    assert any("unavailable" in error for error in errors)


def test_validator_rejects_day_off_exception():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9), time(17)),
        ),
        availability_exceptions=(
            AvailabilityException(date(2026, 11, 30), False),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 9, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 30, 13, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    errors = validate_schedule(
        [employee],
        [shift],
        {1: [1]},
    )

    assert any("unavailable" in error for error in errors)


def test_validator_accepts_exception_working_hours():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9), time(17)),
        ),
        availability_exceptions=(
            AvailabilityException(
                date(2026, 11, 30),
                True,
                ((time(13), time(17)),),
            ),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 13, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 30, 17, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert validate_schedule(
        [employee],
        [shift],
        {1: [1]},
    ) == []
