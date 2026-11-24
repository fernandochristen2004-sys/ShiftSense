"""Planning periods: one local week, starting Monday at 00:00."""

from datetime import date, datetime, time, timedelta, tzinfo


def week_bounds(week_start: date, restaurant_timezone: tzinfo) -> tuple[datetime, datetime]:
    """Return the start and end of the planning week as aware datetimes.

    `week_start` must be a Monday in the restaurant's local calendar. The end
    is the next Monday at 00:00 local time, so a week containing a daylight
    saving change is still exactly one local week.
    """
    if type(week_start) is not date:
        raise ValueError("Week start must be a date.")
    if week_start.weekday() != 0:
        raise ValueError("Planning weeks start on a Monday.")

    start = datetime.combine(week_start, time(0, 0), tzinfo=restaurant_timezone)
    end = datetime.combine(week_start + timedelta(days=7), time(0, 0), tzinfo=restaurant_timezone)
    return start, end
