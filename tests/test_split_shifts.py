from datetime import datetime, timedelta, timezone
from optimizer.models import DateTimeShift, ShiftRequirement, Employee, SchedulingPolicy, FixedAssignment
from optimizer.timeutils import datetime_shifts_violate_rest_policy
from optimizer.solver import generate_schedule
from optimizer.validator import validate_schedule
from optimizer.lock_conflicts import find_lock_conflicts
import pytest

BASE = datetime(2026, 11, 23, tzinfo=timezone.utc)


def make_shift(
    shift_id: int,
    start_hour: int,
    end_hour: int,
    start_minute: int = 0,
) -> DateTimeShift:
    """Create a shift using elapsed hours from the same UTC base."""
    return DateTimeShift(
        id=shift_id,
        starts_at=BASE + timedelta(
            hours=start_hour,
            minutes=start_minute,
        ),
        ends_at=BASE + timedelta(hours=end_hour),
        requirements=(ShiftRequirement("server", 1),),
    )


def violates_rest(
    first: DateTimeShift,
    second: DateTimeShift,
    allow_split: bool,
) -> bool:
    return datetime_shifts_violate_rest_policy(
        first,
        second,
        minimum_rest_minutes=660,
        allow_split_shifts=allow_split,
        split_shift_min_break_minutes=120,
        max_split_span_minutes=780,
    )


def test_lunch_dinner_split_allowed_when_enabled():
    lunch = make_shift(1, 11, 15)
    dinner = make_shift(2, 17, 23)

    assert violates_rest(lunch, dinner, True) is False
    assert violates_rest(lunch, dinner, False) is True


def test_split_break_below_minimum_is_rejected():
    lunch = make_shift(1, 11, 15)
    dinner = make_shift(2, 16, 23, start_minute=59)

    assert violates_rest(lunch, dinner, True) is True


def test_split_break_exactly_two_hours_is_allowed():
    lunch = make_shift(1, 11, 15)
    dinner = make_shift(2, 17, 23)

    assert violates_rest(lunch, dinner, True) is False


def test_overnight_close_to_lunch_is_rejected():
    close = make_shift(1, 20, 26)
    lunch = make_shift(2, 35, 39)

    assert violates_rest(close, lunch, True) is True


def test_three_segments_exceeding_span_are_rejected():
    first = make_shift(1, 8, 10)
    middle = make_shift(2, 12, 14)
    last = make_shift(3, 16, 22)

    assert violates_rest(first, middle, True) is False
    assert violates_rest(middle, last, True) is False
    assert violates_rest(first, last, True) is True


def test_exact_maximum_split_span_is_allowed():
    first = make_shift(1, 10, 14)
    second = make_shift(2, 16, 23)

    assert violates_rest(first, second, True) is False


def test_span_one_minute_above_maximum_is_rejected():
    first = make_shift(1, 10, 14)
    second = make_shift(2, 16, 23, start_minute=0)

    # Extend the second shift by one minute.
    second = DateTimeShift(
        id=2,
        starts_at=second.starts_at,
        ends_at=second.ends_at + timedelta(minutes=1),
        requirements=second.requirements,
    )

    assert violates_rest(first, second, True) is True


def test_normal_rest_overrides_split_span_limit():
    first = make_shift(1, 8, 12)
    second = make_shift(2, 23, 27)

    assert violates_rest(first, second, True) is False


def make_employee(max_hours: int = 16) -> Employee:
    """Create an employee available throughout the test period."""
    return Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=max_hours,
        datetime_availability=(
            (BASE, BASE + timedelta(days=3)),
        ),
    )


def split_policy(enabled: bool = True) -> SchedulingPolicy:
    return SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
        fairness_enabled=False,
        allow_split_shifts=enabled,
        split_shift_min_break_minutes=120,
        max_split_span_minutes=780,
    )


def test_solver_allows_valid_lunch_dinner_split():
    employees = [make_employee()]
    shifts = [
        make_shift(1, 11, 15),
        make_shift(2, 17, 23),
    ]
    policy = split_policy()

    result = generate_schedule(employees, shifts, policy=policy)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments == {
        1: {"server": [1]},
        2: {"server": [1]},
    }

    assert validate_schedule(
        employees, shifts, result.assignments, policy=policy
    ) == []


def test_solver_blocks_split_when_disabled():
    result = generate_schedule(
        [make_employee()],
        [make_shift(1, 11, 15), make_shift(2, 17, 23)],
        policy=split_policy(enabled=False),
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_solver_rejects_short_split_break():
    result = generate_schedule(
        [make_employee()],
        [
            make_shift(1, 11, 15),
            make_shift(2, 16, 23, start_minute=59),
        ],
        policy=split_policy(),
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_solver_rejects_overnight_short_turnaround():
    result = generate_schedule(
        [make_employee()],
        [
            make_shift(1, 20, 26),
            make_shift(2, 35, 39),
        ],
        policy=split_policy(),
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_solver_rejects_three_segment_span_violation():
    result = generate_schedule(
        [make_employee()],
        [
            make_shift(1, 8, 10),
            make_shift(2, 12, 14),
            make_shift(3, 16, 22),
        ],
        policy=split_policy(),
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_split_shifts_still_respect_max_hours():
    result = generate_schedule(
        [make_employee(max_hours=9)],
        [
            make_shift(1, 11, 15),
            make_shift(2, 17, 23),
        ],
        policy=split_policy(),
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_outside_assignment_can_form_valid_split():
    employee = make_employee()
    lunch = make_shift(100, 11, 15)
    dinner = make_shift(1, 17, 23)

    outside = (
        FixedAssignment(
            employee_id=1,
            shift=lunch,
        ),
    )

    policy = split_policy()

    result = generate_schedule(
        [employee],
        [dinner],
        policy=policy,
        outside_assignments=outside,
    )

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments == {
        1: {"server": [1]},
    }

    assert validate_schedule(
        [employee],
        [dinner],
        result.assignments,
        policy=policy,
        outside_assignments=outside,
    ) == []


def test_outside_assignment_blocks_invalid_split():
    employee = make_employee()
    close = make_shift(100, 20, 26)
    lunch = make_shift(1, 35, 39)

    outside = (
        FixedAssignment(
            employee_id=1,
            shift=close,
        ),
    )

    result = generate_schedule(
        [employee],
        [lunch],
        policy=split_policy(),
        outside_assignments=outside,
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None


def test_valid_locked_split_has_no_conflicts():
    employee = make_employee()
    shifts = [
        make_shift(1, 11, 15),
        make_shift(2, 17, 23),
    ]

    locks = {
        1: {"server": [1]},
        2: {"server": [1]},
    }

    policy = split_policy()

    result = generate_schedule(
        [employee],
        shifts,
        policy=policy,
        locked_assignments=locks,
    )

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None

    assert validate_schedule(
        [employee],
        shifts,
        result.assignments,
        policy=policy,
        locked_assignments=locks,
    ) == []


def test_invalid_locked_split_reports_rest_conflict():
    employee = make_employee()
    shifts = [
        make_shift(1, 20, 26),
        make_shift(2, 35, 39),
    ]

    locks = {
        1: {"server": [1]},
        2: {"server": [1]},
    }

    result = generate_schedule(
        [employee],
        shifts,
        policy=split_policy(),
        locked_assignments=locks,
    )

    assert result.status == "INFEASIBLE"
    assert result.assignments is None
    assert any(
        "minimum rest" in conflict
        for conflict in result.conflicts
    )


def test_split_shifts_disabled_by_default():
    policy = SchedulingPolicy()

    assert policy.allow_split_shifts is False
    assert policy.split_shift_min_break_minutes == 120
    assert policy.max_split_span_minutes == 780


def test_split_policy_rejects_invalid_break():
    for invalid_break in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            SchedulingPolicy(
                split_shift_min_break_minutes=invalid_break,
            )


def test_split_policy_rejects_invalid_span():
    for invalid_span in (0, 120, -1, 1.5, True):
        with pytest.raises(ValueError):
            SchedulingPolicy(
                max_split_span_minutes=invalid_span,
            )


def test_split_policy_rejects_break_not_shorter_than_rest():
    with pytest.raises(ValueError):
        SchedulingPolicy(
            minimum_rest_hours=2,
            enforce_minimum_rest=True,
            allow_split_shifts=True,
            split_shift_min_break_minutes=120,
        )


def test_split_policy_rejects_invalid_enabled_flag():
    with pytest.raises(ValueError):
        SchedulingPolicy(allow_split_shifts="yes")


def test_shift_rejects_subminute_precision():
    with pytest.raises(
        ValueError,
        match="minute precision",
    ):
        DateTimeShift(
            id=2,
            starts_at=BASE + timedelta(
                hours=16,
                minutes=59,
                seconds=59,
            ),
            ends_at=BASE + timedelta(hours=23),
            requirements=(
                ShiftRequirement("server", 1),
            ),
        )


def test_split_rest_with_different_timezones():
    malaysia = timezone(timedelta(hours=8))

    lunch = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 23, 19, tzinfo=malaysia
        ),
        ends_at=datetime(
            2026, 11, 23, 23, tzinfo=malaysia
        ),
        requirements=(ShiftRequirement("server", 1),),
    )

    dinner = make_shift(2, 26, 32)

    # Lunch ends at 15:00 UTC.
    # Dinner starts at 02:00 UTC the next day.
    # Exactly 11 hours of normal rest.
    assert violates_rest(lunch, dinner, True) is False


def test_lock_diagnostics_accept_valid_split():
    employee = make_employee()
    shifts = [
        make_shift(1, 11, 15),
        make_shift(2, 17, 23),
    ]

    locks = {
        1: {"server": [1]},
        2: {"server": [1]},
    }

    conflicts = find_lock_conflicts(
        employees=[employee],
        shifts=shifts,
        locked_assignments=locks,
        policy=split_policy(),
    )

    assert conflicts == ()
