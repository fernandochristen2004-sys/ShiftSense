"""When each employee can work: weekly hours and date exceptions.

Weekly rules repeat every week, in restaurant time. A rule that ends earlier
than it starts (22:00-02:00) crosses midnight. Someone with no weekly rules
and no exceptions is never available.

A date exception replaces the weekly rules for that one date: either off all
day, or available only in the listed same-day windows.

The engine's own models check every rule, so the API and the solver agree
on what is valid. Like the other services, these never commit.
"""

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import models as db
from optimizer.models import AvailabilityException, WeeklyAvailability
from services.staff import get_staff_member

MAX_RULES = 50
MAX_INTERVALS = 10


@dataclass(frozen=True)
class DateException:
    date: date
    available: bool
    intervals: tuple[tuple[time, time], ...]
    note: str | None


@dataclass(frozen=True)
class Availability:
    weekly: tuple[WeeklyAvailability, ...]  # by weekday, then start time
    exceptions: tuple[DateException, ...]   # by date


def get_availability(session: Session, restaurant_id: int, employee_id: int) -> Availability:
    get_staff_member(session, restaurant_id, employee_id)  # 404 if not theirs

    weekly = tuple(
        WeeklyAvailability(rule.weekday, rule.start_time, rule.end_time)
        for rule in session.scalars(
            select(db.AvailabilityRule)
            .where(db.AvailabilityRule.employee_id == employee_id)
            .order_by(db.AvailabilityRule.weekday, db.AvailabilityRule.start_time)
        )
    )

    rows = session.scalars(
        select(db.AvailabilityException)
        .where(db.AvailabilityException.employee_id == employee_id)
        .order_by(db.AvailabilityException.local_date)
    ).all()
    intervals: dict[int, list[tuple[time, time]]] = {}
    for interval in session.scalars(
        select(db.AvailabilityExceptionInterval)
        .where(db.AvailabilityExceptionInterval.exception_id.in_([r.id for r in rows]))
        .order_by(db.AvailabilityExceptionInterval.start_time)
    ):
        intervals.setdefault(interval.exception_id, []).append(
            (interval.start_time, interval.end_time)
        )

    return Availability(
        weekly=weekly,
        exceptions=tuple(
            DateException(row.local_date, row.available, tuple(intervals.get(row.id, ())), row.note)
            for row in rows
        ),
    )


def replace_weekly(
    session: Session,
    restaurant_id: int,
    employee_id: int,
    rules: list[tuple[int, time, time]],
) -> Availability:
    """Replace someone's weekly hours with these (weekday, start, end) rules."""
    get_staff_member(session, restaurant_id, employee_id)
    if len(rules) > MAX_RULES:
        raise ValueError(f"At most {MAX_RULES} weekly rules.")
    checked = sorted({WeeklyAvailability(*rule) for rule in rules},  # engine checks; drops repeats
                     key=lambda r: (r.weekday, r.start_time, r.end_time))

    for row in session.scalars(
        select(db.AvailabilityRule).where(db.AvailabilityRule.employee_id == employee_id)
    ):
        session.delete(row)
    session.flush()
    session.add_all(
        db.AvailabilityRule(
            employee_id=employee_id,
            weekday=rule.weekday,
            start_time=rule.start_time,
            end_time=rule.end_time,
        )
        for rule in checked
    )
    session.flush()
    return get_availability(session, restaurant_id, employee_id)


def set_exception(
    session: Session,
    restaurant_id: int,
    employee_id: int,
    local_date: date,
    available: bool,
    intervals: list[tuple[time, time]],
    note: str | None = None,
) -> Availability:
    """Set (or replace) the exception for one date.

    available=False means off all day (send no intervals). available=True
    means only the given same-day windows.
    """
    get_staff_member(session, restaurant_id, employee_id)
    if len(intervals) > MAX_INTERVALS:
        raise ValueError(f"At most {MAX_INTERVALS} time windows on one date.")
    checked = AvailabilityException(  # the engine's checks
        date=local_date,
        available=available,
        intervals=tuple(sorted(set(intervals))),
    )

    existing = _exception_row(session, employee_id, local_date)
    if existing is not None:
        session.delete(existing)  # its windows go with it (on delete cascade)
        session.flush()

    row = db.AvailabilityException(
        employee_id=employee_id,
        local_date=local_date,
        available=available,
        note=(note or "").strip() or None,
    )
    session.add(row)
    session.flush()
    session.add_all(
        db.AvailabilityExceptionInterval(exception_id=row.id, start_time=start, end_time=end)
        for start, end in checked.intervals
    )
    session.flush()
    return get_availability(session, restaurant_id, employee_id)


def remove_exception(
    session: Session, restaurant_id: int, employee_id: int, local_date: date
) -> None:
    """Go back to the weekly hours for that date."""
    get_staff_member(session, restaurant_id, employee_id)
    row = _exception_row(session, employee_id, local_date)
    if row is None:
        raise LookupError(f"No exception on {local_date.isoformat()}.")
    session.delete(row)
    session.flush()


def _exception_row(session: Session, employee_id: int, local_date: date):
    return session.scalars(
        select(db.AvailabilityException).where(
            db.AvailabilityException.employee_id == employee_id,
            db.AvailabilityException.local_date == local_date,
        )
    ).one_or_none()
