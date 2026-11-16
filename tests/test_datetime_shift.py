from datetime import datetime, timezone, timedelta

import pytest

from optimizer.models import DateTimeShift


def test_datetime_shift_supports_overnight():
    shift = DateTimeShift(
        id=1,
        starts_at=datetime(
            2026, 11, 21, 20, 30, tzinfo=timezone.utc
        ),
        ends_at=datetime(
            2026, 11, 22, 2, 15, tzinfo=timezone.utc
        ),
        required_staff=2,
        required_skill="server",
    )

    duration = shift.ends_at - shift.starts_at

    assert duration == timedelta(hours=5, minutes=45)


def test_datetime_shift_rejects_end_before_start():
    with pytest.raises(ValueError):
        DateTimeShift(
            id=1,
            starts_at=datetime(
                2026, 11, 21, 17, 0, tzinfo=timezone.utc
            ),
            ends_at=datetime(
                2026, 11, 21, 9, 0, tzinfo=timezone.utc
            ),
            required_staff=1,
            required_skill="server",
        )


def test_datetime_shift_rejects_naive_datetime():
    with pytest.raises(ValueError):
        DateTimeShift(
            id=1,
            starts_at=datetime(2026, 11, 21, 9, 0),
            ends_at=datetime(
                2026, 11, 21, 17, 0, tzinfo=timezone.utc
            ),
            required_staff=1,
            required_skill="server",
        )

def test_datetime_shift_rejects_seconds():
    with pytest.raises(ValueError):
        DateTimeShift(
            id=1,
            starts_at=datetime(
                2026, 11, 21, 9, 0, 30,
                tzinfo=timezone.utc,
            ),
            ends_at=datetime(
                2026, 11, 21, 17, 0,
                tzinfo=timezone.utc,
            ),
            required_staff=1,
            required_skill="server",
        )