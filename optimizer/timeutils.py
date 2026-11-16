from optimizer.models import DateTimeShift
from datetime import datetime, timezone

def minutes_from_start(
    timestamp: datetime,
    period_start: datetime,
) -> int:
    """Return whole minutes from the scheduling period start."""

    if timestamp.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware.")

    if period_start.utcoffset() is None:
        raise ValueError("Period start must be timezone-aware.")

    elapsed = (
        timestamp.astimezone(timezone.utc)
        - period_start.astimezone(timezone.utc)
    )

    total_seconds = elapsed.total_seconds()

    if total_seconds % 60 != 0:
        raise ValueError(
            "Datetime must have whole-minute precision."
        )

    return int(total_seconds // 60)

def datetime_shifts_overlap(
    first: DateTimeShift,
    second: DateTimeShift,
) -> bool:
    """Check whether two datetime-based shifts overlap."""
    return (
        first.starts_at < second.ends_at
        and second.starts_at < first.ends_at
    )

def datetime_shifts_violate_minimum_rest(
    first: DateTimeShift,
    second: DateTimeShift,
    minimum_rest_minutes: int,
) -> bool:
    """Check minimum rest between two non-overlapping shifts."""

    # Overlapping shifts are handled by a separate constraint.
    if datetime_shifts_overlap(first, second):
        return False

    # Identify which shift comes first chronologically.
    if first.starts_at <= second.starts_at:
        earlier = first
        later = second
    else:
        earlier = second
        later = first

    # Calculate actual elapsed rest time in minutes.
    rest_duration = (
        later.starts_at.astimezone(timezone.utc)
        - earlier.ends_at.astimezone(timezone.utc)
    )

    rest_minutes = int(
        rest_duration.total_seconds() // 60
    )

    return rest_minutes < minimum_rest_minutes

def shift_duration_minutes(shift: DateTimeShift) -> int:
    """Return the shift duration in whole minutes."""
    duration = (
        shift.ends_at.astimezone(timezone.utc)
        - shift.starts_at.astimezone(timezone.utc)
    )

    return int(duration.total_seconds() // 60)

def shift_fits_interval(
    shift: DateTimeShift,
    interval_start: datetime,
    interval_end: datetime,
) -> bool:
    """Check whether a shift fits entirely inside an interval."""

    if interval_start.utcoffset() is None:
        raise ValueError("Interval start must be timezone-aware.")

    if interval_end.utcoffset() is None:
        raise ValueError("Interval end must be timezone-aware.")

    if interval_end <= interval_start:
        raise ValueError("Interval end must be after its start.")

    return (
        interval_start <= shift.starts_at
        and shift.ends_at <= interval_end
    )