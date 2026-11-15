from optimizer.repair import count_assignment_changes
from optimizer.models import Employee, Shift, Availability, SchedulingPolicy
from optimizer.solver import generate_schedule
import pytest

def test_count_assignment_changes():
    original_schedule = {
        1: [2, 4],
        2: [3],
    }

    repaired_schedule = {
        1: [1, 4],
        2: [3],
    }

    changes = count_assignment_changes(
        original_schedule,
        repaired_schedule,
    )

    assert changes == 2

def test_repair_employee_absence():
    # Two employees are qualified to work as servers.
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
            skills=frozenset({"server"}),
            max_hours=16,
            available_days=frozenset(),
        ),
    ]

    # One shift requires a server.
    test_shifts = [
        Shift(
            id=1,
            day=0,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        ),
    ]

    # Bob was assigned before becoming unavailable.
    original_schedule = {
        1: [2],
    }

    # Repair the schedule using updated availability.
    result = generate_schedule(
        test_employees,
        test_shifts,
        original_schedule=original_schedule,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Alice must replace Bob.
    assert result.assignments == {1: [1]}

    # Removing Bob and adding Alice counts as two changes.
    changes = count_assignment_changes(
        original_schedule,
        result.assignments,
    )

    assert changes == 2

def test_repair_preserves_unaffected_assignments():
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
            skills=frozenset({"server"}),
            max_hours=16,
            available_days=frozenset(),
        ),
        Employee(
            id=3,
            name="Charlie",
            skills=frozenset({"server"}),
            max_hours=16,
        ),
        Employee(
            id=4,
            name="Diana",
            skills=frozenset({"server"}),
            max_hours=16,
        ),
    ]

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
        Shift(
            id=3,
            day=2,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        ),
    ]

    # Bob calls out, but Charlie and Diana should keep their shifts.
    original_schedule = {
        1: [2],
        2: [3],
        3: [4],
    }

    result = generate_schedule(
        test_employees,
        test_shifts,
        original_schedule=original_schedule,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # The original unaffected assignments must remain unchanged.
    assert result.assignments[2] == [3]
    assert result.assignments[3] == [4]

    # Alice should replace Bob.
    assert result.assignments[1] == [1]

    # Only Bob's removal and Alice's addition should be counted.
    changes = count_assignment_changes(
        original_schedule,
        result.assignments,
    )

    assert changes == 2

def test_repair_requires_multiple_assignment_changes():
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=4,
            availability=(
                Availability(day=0, start_hour=9, end_hour=17),
            ),
        ),
        Employee(
            id=2,
            name="Bob",
            skills=frozenset({"server"}),
            max_hours=8,
            available_days=frozenset(),
        ),
        Employee(
            id=3,
            name="Charlie",
            skills=frozenset({"server"}),
            max_hours=8,
            availability=(
                Availability(day=0, start_hour=13, end_hour=17),
                Availability(day=1, start_hour=9, end_hour=13),
            ),
        ),
    ]

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
            start_hour=13,
            end_hour=17,
            required_staff=1,
            required_skill="server",
        ),
        Shift(
            id=3,
            day=1,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        ),
    ]

    original_schedule = {
        1: [2],
        2: [1],
        3: [3],
    }

    result = generate_schedule(
        test_employees,
        test_shifts,
        original_schedule=original_schedule,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Alice moves to Monday morning.
    assert result.assignments[1] == [1]

    # Charlie takes Monday afternoon.
    assert result.assignments[2] == [3]

    # Charlie keeps Tuesday morning.
    assert result.assignments[3] == [3]

    changes = count_assignment_changes(
        original_schedule,
        result.assignments,
    )

    assert changes == 4

def test_repair_uses_fairness_to_break_ties():
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=12,
        ),
        Employee(
            id=2,
            name="Bob",
            skills=frozenset({"server"}),
            max_hours=12,
            available_days=frozenset(),
        ),
        Employee(
            id=3,
            name="Charlie",
            skills=frozenset({"server"}),
            max_hours=12,
        ),
    ]

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
        Shift(
            id=3,
            day=2,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        ),
    ]

    # Bob calls out of Shift 3.
    original_schedule = {
        1: [1],
        2: [1],
        3: [2],
    }

    result = generate_schedule(
        test_employees,
        test_shifts,
        original_schedule=original_schedule,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Alice keeps both existing shifts.
    assert result.assignments[1] == [1]
    assert result.assignments[2] == [1]

    # Charlie replaces Bob rather than giving Alice more hours.
    assert result.assignments[3] == [3]

    # Only Bob's removal and Charlie's addition are needed.
    assert count_assignment_changes(
        original_schedule,
        result.assignments,
    ) == 2

def test_repair_prioritizes_minimum_disruption():
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
            skills=frozenset({"server"}),
            max_hours=16,
            available_days=frozenset(),
        ),
        Employee(
            id=3,
            name="Charlie",
            skills=frozenset({"server"}),
            max_hours=16,
        ),
    ]

    test_shifts = [
        Shift(
            id=shift_id,
            day=shift_id - 1,
            start_hour=9,
            end_hour=13,
            required_staff=1,
            required_skill="server",
        )
        for shift_id in range(1, 5)
    ]

    # Bob calls out of Shift 4.
    original_schedule = {
        1: [1],
        2: [1],
        3: [1],
        4: [2],
    }

    result = generate_schedule(
        test_employees,
        test_shifts,
        original_schedule=original_schedule,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Alice keeps all three existing assignments.
    assert result.assignments[1] == [1]
    assert result.assignments[2] == [1]
    assert result.assignments[3] == [1]

    # Charlie replaces Bob.
    assert result.assignments[4] == [3]

    # Only one removal and one addition.
    assert count_assignment_changes(
        original_schedule,
        result.assignments,
    ) == 2

@pytest.mark.parametrize(
    "invalid_schedule",
    [
        {1: [1]},           # Missing shift 2
        {1: [1], 2: [2], 3: []},  # Unexpected shift 3
        {1: [1, 1], 2: [2]},     # Duplicate assignment
        {1: [99], 2: [2]},      # Unknown employee
    ],
)
def test_repair_rejects_invalid_original_schedule(invalid_schedule):
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
            skills=frozenset({"server"}),
            max_hours=16,
        ),
    ]

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

    with pytest.raises(ValueError):
        generate_schedule(
            test_employees,
            test_shifts,
            original_schedule=invalid_schedule,
        )

def test_repair_with_no_shifts():
    test_employees = [
        Employee(
            id=1,
            name="Alice",
            skills=frozenset({"server"}),
            max_hours=16,
        )
    ]

    result = generate_schedule(
        test_employees,
        [],
        original_schedule={},
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {}

def test_repair_with_fairness_disabled():
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
            skills=frozenset({"server"}),
            max_hours=16,
            available_days=frozenset(),
        ),
        Employee(
            id=3,
            name="Charlie",
            skills=frozenset({"server"}),
            max_hours=16,
        ),
    ]

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

    original_schedule = {
        1: [2],
        2: [1],
    }

    policy = SchedulingPolicy(fairness_enabled=False)

    result = generate_schedule(
        test_employees,
        test_shifts,
        original_schedule=original_schedule,
        policy=policy,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None

    # Alice's existing assignment must be preserved.
    assert result.assignments[2] == [1]

    # Bob must be replaced.
    assert result.assignments[1] == [3]

    # One removal and one addition.
    assert count_assignment_changes(
        original_schedule,
        result.assignments,
    ) == 2