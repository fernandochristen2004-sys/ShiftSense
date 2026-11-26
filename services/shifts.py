"""Managing a restaurant's shifts and how many people each one needs.

Managers think in restaurant time, so shifts are given as a local date,
start and end. An end earlier than the start means the shift ends the next
day (23:00-02:00).

A shift people have been told about (it's on a published or archived
schedule) can't be moved or re-staffed: that would rewrite what they saw.
Cancel it and add a new one instead; the next repair sorts out the staff.

Like the other services, these never commit.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from db import models as db
from services.errors import ConflictError
from services.loading import load_restaurant
from services.staff import clean_name, skill_ids

MAX_SHIFT_HOURS = 16
UNSET = object()


@dataclass(frozen=True)
class Need:
    role: str
    count: int
    min_count: int | None = None  # None = the same as count (no shortfall allowed)


def create_shift(
    session: Session,
    restaurant_id: int,
    *,
    local_date: date,
    start_time: time,
    end_time: time,
    needs: list[Need],
    label: str | None = None,
) -> db.Shift:
    restaurant = load_restaurant(session, restaurant_id)
    starts_at, ends_at = _bounds(local_date, start_time, end_time, ZoneInfo(restaurant.timezone))
    resolved = _resolve_needs(session, restaurant_id, needs)

    shift = db.Shift(
        restaurant_id=restaurant_id,
        label=_clean_label(label),
        starts_at=starts_at,
        ends_at=ends_at,
        status="active",
    )
    session.add(shift)
    session.flush()
    _set_needs(session, shift, resolved)
    return shift


def update_shift(
    session: Session,
    restaurant_id: int,
    shift_id: int,
    *,
    label=UNSET,
    local_date=UNSET,
    start_time=UNSET,
    end_time=UNSET,
    needs=UNSET,
) -> db.Shift:
    """Change only what's given. `needs` replaces the whole list.

    The label can always change. Times and staffing can't once the shift is
    on a published or archived schedule.
    """
    restaurant = load_restaurant(session, restaurant_id)
    shift = _active_shift(session, restaurant_id, shift_id)
    tz = ZoneInfo(restaurant.timezone)

    moving = any(value is not UNSET for value in (local_date, start_time, end_time))
    if (moving or needs is not UNSET) and _was_published(session, shift.id):
        raise ConflictError(
            "This shift is on a published schedule, so its times and staffing can't change. "
            "Cancel it and add a new shift instead."
        )

    # Check everything first, so a refused change leaves the shift untouched.
    starts_at, ends_at = shift.starts_at, shift.ends_at
    if moving:
        local_start, local_end = starts_at.astimezone(tz), ends_at.astimezone(tz)
        starts_at, ends_at = _bounds(
            local_start.date() if local_date is UNSET else local_date,
            local_start.time() if start_time is UNSET else start_time,
            local_end.time() if end_time is UNSET else end_time,
            tz,
        )
    resolved = None if needs is UNSET else _resolve_needs(session, restaurant_id, needs)

    if label is not UNSET:
        shift.label = _clean_label(label)
    shift.starts_at, shift.ends_at = starts_at, ends_at
    session.flush()
    if resolved is not None:
        _set_needs(session, shift, resolved)
    return shift


def remove_shift(session: Session, restaurant_id: int, shift_id: int) -> str:
    """Take a shift off the rota. Returns "deleted" or "cancelled".

    A shift nothing refers to is deleted. One that's on a schedule or has a
    call-out is marked cancelled, so older revisions still make sense; new
    drafts and repairs leave it out.
    """
    shift = _active_shift(session, restaurant_id, shift_id)
    used = session.scalar(select(
        exists().where(db.Assignment.shift_id == shift.id)
        | exists().where(db.Absence.shift_id == shift.id)
        | exists().where(db.Lock.shift_id == shift.id)
    ))
    if used:
        shift.status = "cancelled"
        session.flush()
        return "cancelled"

    session.delete(shift)  # its requirements go with it (on delete cascade)
    session.flush()
    return "deleted"


def shift_needs(session: Session, shift_ids: list[int]) -> dict[int, list[Need]]:
    """shift id -> its needs, roles A to Z."""
    result: dict[int, list[Need]] = {i: [] for i in shift_ids}
    for shift_id, role, count, min_count in session.execute(
        select(
            db.ShiftRequirement.shift_id,
            db.Skill.name,
            db.ShiftRequirement.count,
            db.ShiftRequirement.min_count,
        )
        .join(db.Skill, db.Skill.id == db.ShiftRequirement.skill_id)
        .where(db.ShiftRequirement.shift_id.in_(shift_ids))
        .order_by(db.ShiftRequirement.shift_id, db.Skill.name)
    ):
        result[shift_id].append(Need(role, count, min_count))
    return result


# Helpers

def _active_shift(session: Session, restaurant_id: int, shift_id: int) -> db.Shift:
    shift = session.get(db.Shift, shift_id)
    if shift is None or shift.restaurant_id != restaurant_id or shift.status != "active":
        raise LookupError(f"Shift {shift_id} not found.")
    return shift


def _was_published(session: Session, shift_id: int) -> bool:
    return bool(session.scalar(select(exists().where(
        db.Assignment.shift_id == shift_id,
        db.Assignment.schedule_id == db.Schedule.id,
        db.Schedule.status.in_(("published", "archived")),
    ))))


def _bounds(local_date: date, start: time, end: time, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Local date and times to aware datetimes. An earlier end is the next day."""
    for value in (start, end):
        if value.second or value.microsecond:
            raise ValueError("Shift times must be whole minutes.")
        if value.tzinfo is not None:
            raise ValueError("Give shift times in restaurant time, without a timezone.")
    if start == end:
        raise ValueError("A shift can't start and end at the same time.")

    starts_at = datetime.combine(local_date, start, tzinfo=tz)
    end_date = local_date if end > start else local_date + timedelta(days=1)
    ends_at = datetime.combine(end_date, end, tzinfo=tz)

    if ends_at - starts_at > timedelta(hours=MAX_SHIFT_HOURS):
        raise ValueError(f"A shift can be at most {MAX_SHIFT_HOURS} hours long.")
    return starts_at, ends_at


def _clean_label(label: str | None) -> str | None:
    return " ".join((label or "").split()) or None


def _resolve_needs(
    session: Session, restaurant_id: int, needs: list[Need]
) -> list[tuple[int, int, int]]:
    """Needs to (skill_id, count, min_count), checked."""
    if not needs:
        raise ValueError("A shift needs at least one role.")

    names = [clean_name(need.role, "Role name") for need in needs]
    if len(set(names)) != len(names):
        raise ValueError("Each role can be listed only once per shift.")
    ids = skill_ids(session, restaurant_id, names)
    unknown = sorted(set(names) - ids.keys())
    if unknown:
        raise ValueError("Unknown role(s): " + ", ".join(unknown) + ". Add them as roles first.")

    resolved = []
    for name, need in zip(names, needs):
        min_count = need.count if need.min_count is None else need.min_count
        if need.count < 1:
            raise ValueError(f"{name}: a shift needs at least 1 person in each role it lists.")
        if not 0 <= min_count <= need.count:
            raise ValueError(f"{name}: the minimum must be between 0 and {need.count}.")
        resolved.append((ids[name], need.count, min_count))
    return resolved


def _set_needs(session: Session, shift: db.Shift, resolved: list[tuple[int, int, int]]) -> None:
    for row in session.scalars(
        select(db.ShiftRequirement).where(db.ShiftRequirement.shift_id == shift.id)
    ):
        session.delete(row)
    session.flush()
    session.add_all(
        db.ShiftRequirement(
            restaurant_id=shift.restaurant_id,
            shift_id=shift.id,
            skill_id=skill_id,
            count=count,
            min_count=min_count,
        )
        for skill_id, count, min_count in resolved
    )
    session.flush()
