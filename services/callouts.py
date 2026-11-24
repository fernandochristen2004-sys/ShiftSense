"""Call-outs: who can't work, and for how long.

Shared by the API (call-outs sent in a request) and the database workflows
(call-outs stored as absences), so both behave exactly the same way.
"""

from collections.abc import Iterable
from datetime import datetime, time, timedelta, tzinfo
from typing import Protocol


class TimedShift(Protocol):
    starts_at: datetime
    ends_at: datetime


def callout_window(
    shift: TimedShift,
    scheduling_timezone: tzinfo,
    rest_of_day: bool = True,
) -> tuple[datetime, datetime]:
    """The period a call-out keeps the employee off work.

    By default: from the shift's start until 06:00 the next morning in the
    restaurant's timezone (or the shift's end, if later). With
    `rest_of_day=False`, only the shift itself.
    """
    if not rest_of_day:
        return shift.starts_at, shift.ends_at

    local_start = shift.starts_at.astimezone(scheduling_timezone)
    next_morning = datetime.combine(
        local_start.date() + timedelta(days=1),
        time(6, 0),
        tzinfo=scheduling_timezone,
    )
    return shift.starts_at, max(shift.ends_at, next_morning)


def exclusions_for_callouts(
    callouts: Iterable[tuple[int, TimedShift, bool]],
    shifts: Iterable[TimedShift],
    scheduling_timezone: tzinfo,
) -> dict[int, list[int]]:
    """Turn (employee_id, shift, rest_of_day) call-outs into engine exclusions.

    Returns {shift_id: [employee_id, ...]} for every shift that overlaps
    each call-out's window.
    """
    shifts = list(shifts)
    excluded: dict[int, list[int]] = {}

    for employee_id, called_shift, rest_of_day in callouts:
        start, end = callout_window(called_shift, scheduling_timezone, rest_of_day)
        for shift in shifts:
            if shift.starts_at < end and start < shift.ends_at:
                ids = excluded.setdefault(shift.id, [])
                if employee_id not in ids:
                    ids.append(employee_id)

    return excluded


def merge_exclusions(
    *groups: dict[int, list[int]] | None,
) -> dict[int, list[int]] | None:
    """Combine exclusion maps without duplicates. None if empty."""
    merged: dict[int, list[int]] = {}
    for group in groups:
        for shift_id, employee_ids in (group or {}).items():
            target = merged.setdefault(shift_id, [])
            target.extend(e for e in employee_ids if e not in target)
    return merged or None
