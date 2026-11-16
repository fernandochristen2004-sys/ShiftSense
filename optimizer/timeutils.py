from optimizer.models import DateTimeShift, WeeklyAvailability, AvailabilityException, Employee
from datetime import datetime, timezone, date, tzinfo, timedelta, time

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


def validate_local_interval(
    start: datetime,
    end: datetime,
) -> None:
    """Reject invalid or ambiguous local scheduling intervals."""

    if start.utcoffset() != end.utcoffset():
        raise ValueError(
            "Availability intervals crossing DST transitions "
            "are not supported."
        )

    for boundary in (start, end):
        # Convert to UTC and back to detect nonexistent local times.
        round_trip = boundary.astimezone(
            timezone.utc
        ).astimezone(boundary.tzinfo)

        if round_trip.replace(fold=boundary.fold) != boundary:
            raise ValueError(
                "Nonexistent local availability time."
            )

        # Reject ambiguous times that occur twice.
        alternate = boundary.replace(fold=1 - boundary.fold)

        if alternate.utcoffset() != boundary.utcoffset():
            raise ValueError(
                "Ambiguous local availability time."
            )


def weekly_rule_interval(
    rule: WeeklyAvailability,
    target_date: date,
    scheduling_timezone: tzinfo,
) -> tuple[datetime, datetime] | None:
    """Convert a matching weekly rule into a datetime interval."""

    if target_date.weekday() != rule.weekday:
        return None

    start = datetime.combine(
        target_date,
        rule.start_time,
        tzinfo=scheduling_timezone,
    )

    end_date = target_date

    # Overnight availability ends on the following calendar day.
    if rule.end_time < rule.start_time:
        end_date += timedelta(days=1)

    end = datetime.combine(
        end_date,
        rule.end_time,
        tzinfo=scheduling_timezone,
    )
    validate_local_interval(start, end)
    return start, end


def exception_intervals(
    exception: AvailabilityException,
    scheduling_timezone: tzinfo,
) -> tuple[tuple[datetime, datetime], ...]:
    """Convert a date-specific exception into datetime intervals."""

    if not exception.available:
        return ()

    intervals = []

    for start_time, end_time in exception.intervals:
        start = datetime.combine(
            exception.date,
            start_time,
            tzinfo=scheduling_timezone,
        )

        end = datetime.combine(
            exception.date,
            end_time,
            tzinfo=scheduling_timezone,
        )

        validate_local_interval(start, end)
        intervals.append((start, end))

    return tuple(intervals)


def find_availability_exception(
    employee: Employee,
    target_date: date,
) -> AvailabilityException | None:
    """Find an employee's availability exception for a date."""

    for exception in employee.availability_exceptions:
        if exception.date == target_date:
            return exception

    return None


def availability_intervals_for_date(
    employee: Employee,
    target_date: date,
    scheduling_timezone: tzinfo,
) -> tuple[tuple[datetime, datetime], ...]:
    """Get availability within one calendar date."""

    day_start = datetime.combine(
        target_date,
        time.min,
        tzinfo=scheduling_timezone,
    )

    next_day_start = datetime.combine(
        target_date + timedelta(days=1),
        time.min,
        tzinfo=scheduling_timezone,
    )

    # Date-specific exceptions override weekly rules.
    exception = find_availability_exception(
        employee,
        target_date,
    )

    if exception is not None:
        intervals = exception_intervals(
            exception,
            scheduling_timezone,
        )
    else:
        intervals = []

        # Include rules starting today and overnight rules
        # carried over from yesterday.
        for rule_date in (
            target_date - timedelta(days=1),
            target_date,
        ):
            for rule in employee.weekly_availability:
                interval = weekly_rule_interval(
                    rule,
                    rule_date,
                    scheduling_timezone,
                )

                if interval is not None:
                    intervals.append(interval)

    # Restrict availability to the requested calendar date.
    clipped = []

    for start, end in intervals:
        clipped_start = max(start, day_start)
        clipped_end = min(end, next_day_start)

        if clipped_start < clipped_end:
            clipped.append((clipped_start, clipped_end))

    return tuple(clipped)


def merge_availability_intervals(
    intervals: tuple[tuple[datetime, datetime], ...],
) -> tuple[tuple[datetime, datetime], ...]:
    """Merge overlapping or adjacent availability intervals."""

    if not intervals:
        return ()

    sorted_intervals = sorted(
        intervals,
        key=lambda interval: interval[0],
    )

    merged = [sorted_intervals[0]]

    for start, end in sorted_intervals[1:]:
        previous_start, previous_end = merged[-1]

        if start <= previous_end:
            merged[-1] = (
                previous_start,
                max(previous_end, end),
            )
        else:
            merged.append((start, end))

    return tuple(merged)

def employee_is_available(
    employee: Employee,
    shift: DateTimeShift,
    scheduling_timezone: tzinfo,
) -> bool:
    """Check whether employee availability covers an entire shift."""

    # Preserve the existing datetime-only availability behavior.
    if (
        not employee.weekly_availability
        and not employee.availability_exceptions
    ):
        if employee.datetime_availability is None:
            return False

        intervals = employee.datetime_availability
        return any(
            shift_fits_interval(shift, start, end)
            for start, end in merge_availability_intervals(intervals)
        )

    # Convert the shift into the scheduling timezone.
    local_start = shift.starts_at.astimezone(scheduling_timezone)
    local_end = shift.ends_at.astimezone(scheduling_timezone)

    # Include every calendar date touched by the shift.
    current_date = local_start.date()
    last_date = local_end.date()

    intervals = []

    while current_date <= last_date:
        intervals.extend(
            availability_intervals_for_date(
                employee,
                current_date,
                scheduling_timezone,
            )
        )

        current_date += timedelta(days=1)

    # Combine adjacent and overlapping intervals.
    merged = merge_availability_intervals(tuple(intervals))

    return any(
        shift_fits_interval(shift, start, end)
        for start, end in merged
    )