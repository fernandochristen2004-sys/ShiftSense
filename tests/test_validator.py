from optimizer.models import Employee, Shift, Availability, SchedulingPolicy
from optimizer.validator import validate_schedule
from optimizer.sample_data import employees, shifts
from optimizer.solver import generate_schedule
import pytest

def test_valid_schedule():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
        )
    ]

    shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        )
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
        )
    ]

    shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        )
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
        )
    ]

    shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        )
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
            availability=(
                Availability(day=0, start_hour=9, end_hour=13),
            ),
        )
    ]

    shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=12,
            end_hour=16,
            required_staff=1,
            required_skill="server",
        )
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
        )
    ]

    shifts = [
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
        )
    ]

    shifts = [
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
        Shift(
            id=3,
            day=2,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        ),
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
            "available_days": frozenset({7}),
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
        {"day": 7},
        {"start_hour": -1},
        {"end_hour": 25},
        {"start_hour": 17, "end_hour": 9},
        {"required_staff": -2},
        {"required_skill": ""},
    ],
)
def test_invalid_shift_data(changes):
    valid_data = {
        "id": 1,
        "day": 0,
        "start_hour": 9,
        "end_hour": 13,
        "required_staff": 1,
        "required_skill": "server",
    }

    valid_data.update(changes)

    with pytest.raises(ValueError):
        Shift(**valid_data)

@pytest.mark.parametrize(
    "changes",
    [
        {"day": -1},
        {"day": 7},
        {"start_hour": -1},
        {"start_hour": 24},
        {"end_hour": 25},
        {"start_hour": 17, "end_hour": 9},
        {"start_hour": 13, "end_hour": 13},
    ],
)
def test_invalid_availability_data(changes):
    valid_data = {
        "day": 0,
        "start_hour": 9,
        "end_hour": 17,
    }

    valid_data.update(changes)

    with pytest.raises(ValueError):
        Availability(**valid_data)

def test_validator_detects_minimum_rest_violation():
    employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
        )
    ]

    shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=17,
            end_hour=23,
            required_staff=1,
            required_skill="server",
        ),
        Shift(
            id=2,
            day=1,
            start_hour=7,
            end_hour=11,
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