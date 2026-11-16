import pytest

from optimizer.models import DateTimeShift
from optimizer.timeutils import (
    minutes_from_start,
    datetime_shifts_overlap,
    datetime_shifts_violate_minimum_rest,
    shift_duration_minutes,
    shift_fits_interval,
)
from datetime import datetime, timedelta, timezone


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
