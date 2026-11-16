import pytest

from optimizer.models import DateTimeShift, WeeklyAvailability, AvailabilityException, Employee
from optimizer.timeutils import (
    minutes_from_start,
    datetime_shifts_overlap,
    datetime_shifts_violate_minimum_rest,
    shift_duration_minutes,
    shift_fits_interval,
    weekly_rule_interval,
    exception_intervals,
    find_availability_exception,
    availability_intervals_for_date,
    merge_availability_intervals,
    employee_is_available,
)
from datetime import datetime, timedelta, timezone, time, date
from zoneinfo import ZoneInfo

@pytest.mark.parametrize(
    "first_day, first_end, second_day, second_start, "
    "minimum_rest, expected",
    [
        (0, 23, 1, 7, 11, True),
        (0, 23, 1, 10, 11, False),
        (0, 23, 1, 12, 11, False),
        (0, 17, 0, 20, 4, True),
        (0, 17, 0, 21, 4, False),
    ],
)
def test_minimum_rest_calculation(
    first_day,
    first_end,
    second_day,
    second_start,
    minimum_rest,
    expected,
):
    base = datetime(2026, 11, 23, tzinfo=timezone.utc)

    first_shift = DateTimeShift(
        id=1,
        starts_at=base + timedelta(days=first_day, hours=9),
        ends_at=base + timedelta(days=first_day, hours=first_end),
        required_staff=1,
        required_skill="server",
    )

    second_shift = DateTimeShift(
        id=2,
        starts_at=base + timedelta(days=second_day, hours=second_start),
        ends_at=base + timedelta(days=second_day, hours=23),
        required_staff=1,
        required_skill="server",
    )

    result = datetime_shifts_violate_minimum_rest(
        first_shift,
        second_shift,
        minimum_rest * 60,
    )

    assert result is expected


def test_minutes_from_start():
    period_start = datetime(
        2026, 11, 21, 0, 0, tzinfo=timezone.utc
    )

    timestamp = datetime(
        2026, 11, 22, 2, 15, tzinfo=timezone.utc
    )

    assert minutes_from_start(timestamp, period_start) == 1575


def test_minutes_from_start_before_period():
    period_start = datetime(
        2026, 11, 21, 0, 0, tzinfo=timezone.utc
    )

    timestamp = datetime(
        2026, 11, 20, 23, 30, tzinfo=timezone.utc
    )

    assert minutes_from_start(timestamp, period_start) == -30


def test_minutes_from_start_rejects_seconds():
    period_start = datetime(
        2026, 11, 21, 0, 0, tzinfo=timezone.utc
    )

    timestamp = datetime(
        2026, 11, 21, 9, 0, 30, tzinfo=timezone.utc
    )

    with pytest.raises(ValueError):
        minutes_from_start(timestamp, period_start)


def test_datetime_shifts_overlap():
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
        required_staff=1,
        required_skill="server",
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
        required_staff=1,
        required_skill="server",
    )

    assert datetime_shifts_overlap(first, second)


@pytest.mark.parametrize(
    "second_start, second_end, expected",
    [
        (2, 6, False),   # Adjacent shifts
        (3, 7, False),   # One-hour gap
        (1, 5, True),    # One-hour overlap
    ],
)
def test_datetime_overlap_boundaries(
    second_start,
    second_end,
    expected,
):
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
        required_staff=1,
        required_skill="server",
    )

    second = DateTimeShift(
        id=2,
        starts_at=datetime(
            2026, 11, 22, second_start, 0,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, second_end, 0,
            tzinfo=timezone.utc,
        ),
        required_staff=1,
        required_skill="server",
    )

    assert datetime_shifts_overlap(first, second) is expected


@pytest.mark.parametrize(
    "second_start, minimum_rest, expected",
    [
        (7, 660, True),     # 5 hours rest, requires 11
        (13, 660, False),   # Exactly 11 hours rest
        (14, 660, False),   # 12 hours rest
        (7, 300, False),    # Exactly 5 hours rest
    ],
)
def test_datetime_minimum_rest(
    second_start,
    minimum_rest,
    expected,
):
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
        required_staff=1,
        required_skill="server",
    )

    second = DateTimeShift(
        id=2,
        starts_at=datetime(
            2026, 11, 22, second_start, 0,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 18, 0,
            tzinfo=timezone.utc,
        ),
        required_staff=1,
        required_skill="server",
    )

    assert datetime_shifts_violate_minimum_rest(
        first,
        second,
        minimum_rest,
    ) is expected


def test_overnight_shift_duration_minutes():
    shift = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 21, 20, 30,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 2, 15,
            tzinfo=timezone.utc,
        ),
        required_staff=1,
        required_skill="server",
    )

    assert shift_duration_minutes(shift) == 345


def test_datetime_shift_fits_availability_interval():
    shift = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 21, 20, 30,
            tzinfo=timezone.utc,
        ),
        ends_at=datetime(
            2026, 11, 22, 2, 15,
            tzinfo=timezone.utc,
        ),
        required_staff=1,
        required_skill="server",
    )

    interval_start = datetime(
        2026, 11, 21, 18, 0,
        tzinfo=timezone.utc,
    )

    interval_end = datetime(
        2026, 11, 22, 3, 0,
        tzinfo=timezone.utc,
    )

    assert shift_fits_interval(
        shift,
        interval_start,
        interval_end,
    )

def test_weekly_rule_interval_matching_day():
    rule = WeeklyAvailability(
        weekday=0,
        start_time=time(9, 0),
        end_time=time(17, 0),
    )

    result = weekly_rule_interval(
        rule,
        date(2026, 11, 30),
        timezone.utc,
    )

    assert result == (
        datetime(2026, 11, 30, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 30, 17, 0, tzinfo=timezone.utc),
    )


def test_weekly_rule_interval_non_matching_day():
    rule = WeeklyAvailability(
        weekday=0,
        start_time=time(9, 0),
        end_time=time(17, 0),
    )

    result = weekly_rule_interval(
        rule,
        date(2026, 12, 1),
        timezone.utc,
    )

    assert result is None

def test_exception_intervals_available():
    exception = AvailabilityException(
        date=date(2026, 11, 30),
        available=True,
        intervals=((time(13, 0), time(17, 0)),),
    )

    result = exception_intervals(
        exception,
        timezone.utc,
    )

    assert result == (
        (
            datetime(2026, 11, 30, 13, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 30, 17, 0, tzinfo=timezone.utc),
        ),
    )


def test_exception_intervals_unavailable():
    exception = AvailabilityException(
        date=date(2026, 11, 30),
        available=False,
    )

    result = exception_intervals(
        exception,
        timezone.utc,
    )

    assert result == ()

def test_find_availability_exception():
    day_off = AvailabilityException(
        date=date(2026, 11, 30),
        available=False,
    )

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        availability_exceptions=(day_off,),
    )

    assert find_availability_exception(
        employee,
        date(2026, 11, 30),
    ) == day_off

    assert find_availability_exception(
        employee,
        date(2026, 12, 1),
    ) is None

def test_availability_intervals_for_date():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(
                weekday=0,
                start_time=time(9, 0),
                end_time=time(17, 0),
            ),
        ),
        availability_exceptions=(
            AvailabilityException(
                date=date(2026, 11, 30),
                available=True,
                intervals=((time(13, 0), time(17, 0)),),
            ),
        ),
    )

    # Normal Monday follows the recurring rule.
    assert availability_intervals_for_date(
        employee,
        date(2026, 11, 23),
        timezone.utc,
    ) == (
        (
            datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc),
        ),
    )

    # The exception overrides the recurring Monday rule.
    assert availability_intervals_for_date(
        employee,
        date(2026, 11, 30),
        timezone.utc,
    ) == (
        (
            datetime(2026, 11, 30, 13, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 30, 17, 0, tzinfo=timezone.utc),
        ),
    )

    # Tuesday has no recurring rule or exception.
    assert availability_intervals_for_date(
        employee,
        date(2026, 12, 1),
        timezone.utc,
    ) == ()

def test_day_off_exception_overrides_weekly_availability():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(
                weekday=0,
                start_time=time(9, 0),
                end_time=time(17, 0),
            ),
        ),
        availability_exceptions=(
            AvailabilityException(
                date=date(2026, 11, 30),
                available=False,
            ),
        ),
    )

    # The normal Monday is available.
    assert availability_intervals_for_date(
        employee,
        date(2026, 11, 23),
        timezone.utc,
    ) != ()

    # The day-off exception overrides Monday availability.
    assert availability_intervals_for_date(
        employee,
        date(2026, 11, 30),
        timezone.utc,
    ) == ()

def test_merge_availability_intervals():
    base = datetime(
        2026, 11, 23, 0, 0,
        tzinfo=timezone.utc,
    )

    def interval(start_hour, end_hour):
        return (
            base + timedelta(hours=start_hour),
            base + timedelta(hours=end_hour),
        )

    # Adjacent intervals should merge.
    assert merge_availability_intervals((
        interval(9, 13),
        interval(13, 17),
    )) == (
        interval(9, 17),
    )

    # Overlapping intervals should merge.
    assert merge_availability_intervals((
        interval(9, 14),
        interval(12, 17),
    )) == (
        interval(9, 17),
    )

    # Intervals with a gap should remain separate.
    assert merge_availability_intervals((
        interval(9, 12),
        interval(14, 17),
    )) == (
        interval(9, 12),
        interval(14, 17),
    )

    # Empty input should produce empty output.
    assert merge_availability_intervals(()) == ()

def test_employee_available_with_weekly_rule():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9, 0), time(17, 0)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 10, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 30, 16, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert employee_is_available(employee, shift, timezone.utc)


def test_employee_unavailable_on_exception_date():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9, 0), time(17, 0)),
        ),
        availability_exceptions=(
            AvailabilityException(date(2026, 11, 30), False),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 10, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 30, 16, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert not employee_is_available(employee, shift, timezone.utc)


def test_employee_available_across_midnight():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(20, 0), time(23, 0)),
            WeeklyAvailability(1, time(0, 0), time(3, 0)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 21, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 2, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    # There is a one-hour availability gap from 23:00 to 00:00.
    assert not employee_is_available(employee, shift, timezone.utc)


def test_employee_available_with_adjacent_intervals():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(9, 0), time(13, 0)),
            WeeklyAvailability(0, time(13, 0), time(17, 0)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 10, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 30, 16, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert employee_is_available(employee, shift, timezone.utc)


def test_employee_legacy_datetime_availability():
    start = datetime(2026, 11, 30, 9, tzinfo=timezone.utc)
    end = datetime(2026, 11, 30, 17, tzinfo=timezone.utc)

    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        datetime_availability=((start, end),),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 10, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 30, 16, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert employee_is_available(employee, shift, timezone.utc)

def test_overnight_shift_with_midnight_gap_is_unavailable():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(20), time(23)),
            WeeklyAvailability(1, time(0), time(3)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 21, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 2, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert not employee_is_available(
        employee,
        shift,
        timezone.utc,
    )

def test_weekly_rule_interval_overnight():
    rule = WeeklyAvailability(
        weekday=0,
        start_time=time(22, 0),
        end_time=time(2, 0),
    )

    result = weekly_rule_interval(
        rule,
        date(2026, 11, 30),
        timezone.utc,
    )

    assert result == (
        datetime(2026, 11, 30, 22, tzinfo=timezone.utc),
        datetime(2026, 12, 1, 2, tzinfo=timezone.utc),
    )


def test_weekly_rule_rejects_equal_times():
    with pytest.raises(ValueError):
        WeeklyAvailability(
            weekday=0,
            start_time=time(9, 0),
            end_time=time(9, 0),
        )


def test_overnight_weekly_availability_covers_next_day():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(22), time(2)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 23, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 1, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert employee_is_available(employee, shift, timezone.utc)


def test_tuesday_day_off_blocks_monday_overnight_shift():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(22), time(2)),
        ),
        availability_exceptions=(
            AvailabilityException(date(2026, 12, 1), False),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 23, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 1, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert not employee_is_available(employee, shift, timezone.utc)


def test_tuesday_exception_can_shorten_overnight_availability():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(22), time(3)),
        ),
        availability_exceptions=(
            AvailabilityException(
                date(2026, 12, 1),
                True,
                ((time(0), time(1)),),
            ),
        ),
    )

    allowed_shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 22, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 1, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    rejected_shift = DateTimeShift(
        id=2,
        starts_at=datetime(2026, 11, 30, 22, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 2, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert employee_is_available(
        employee,
        allowed_shift,
        timezone.utc,
    )

    assert not employee_is_available(
        employee,
        rejected_shift,
        timezone.utc,
    )


def test_dst_transition_requires_explicit_handling():
    new_york = ZoneInfo("America/New_York")

    rule = WeeklyAvailability(
        weekday=6,
        start_time=time(1, 0),
        end_time=time(4, 0),
    )

    with pytest.raises(
        ValueError,
        match="DST transitions",
    ):
        weekly_rule_interval(
            rule,
            date(2026, 3, 8),
            new_york,
        )


def test_rejects_weekly_interval_crossing_dst():
    new_york = ZoneInfo("America/New_York")

    rule = WeeklyAvailability(
        weekday=6,
        start_time=time(1),
        end_time=time(4),
    )

    with pytest.raises(ValueError, match="DST transitions"):
        weekly_rule_interval(
            rule,
            date(2026, 3, 8),
            new_york,
        )


def test_rejects_nonexistent_local_time():
    new_york = ZoneInfo("America/New_York")

    rule = WeeklyAvailability(
        weekday=6,
        start_time=time(2, 30),
        end_time=time(3, 30),
    )

    with pytest.raises(ValueError):
        weekly_rule_interval(
            rule,
            date(2026, 3, 8),
            new_york,
        )


def test_rejects_ambiguous_local_time():
    new_york = ZoneInfo("America/New_York")

    rule = WeeklyAvailability(
        weekday=6,
        start_time=time(1, 30),
        end_time=time(2, 30),
    )

    with pytest.raises(ValueError):
        weekly_rule_interval(
            rule,
            date(2026, 11, 1),
            new_york,
        )


def test_rejects_exception_interval_crossing_dst():
    new_york = ZoneInfo("America/New_York")

    exception = AvailabilityException(
        date=date(2026, 3, 8),
        available=True,
        intervals=((time(1), time(4)),),
    )

    with pytest.raises(ValueError, match="DST transitions"):
        exception_intervals(
            exception,
            new_york,
        )


def test_exception_only_employee_unavailable_on_other_dates():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        availability_exceptions=(
            AvailabilityException(
                date(2026, 11, 30),
                True,
                ((time(9), time(17)),),
            ),
        ),
    )

    allowed_shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 9, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 30, 13, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    other_shift = DateTimeShift(
        id=2,
        starts_at=datetime(2026, 12, 1, 9, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 13, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert employee_is_available(employee, allowed_shift, timezone.utc)
    assert not employee_is_available(employee, other_shift, timezone.utc)


def test_overnight_availability_ending_at_midnight():
    employee = Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server"}),
        max_hours=20,
        weekly_availability=(
            WeeklyAvailability(0, time(20), time(0)),
        ),
    )

    shift = DateTimeShift(
        id=1,
        starts_at=datetime(2026, 11, 30, 20, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 0, tzinfo=timezone.utc),
        required_staff=1,
        required_skill="server",
    )

    assert employee_is_available(employee, shift, timezone.utc)