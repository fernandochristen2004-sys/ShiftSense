"""Starting a week from another one: copy a past week, or use a saved template.

Both work from a week plan: each shift's weekday, local times, name and the
people it needs, without dates or staff. Applying a plan creates those shifts
in another week; the solver then staffs them as usual.

A plan is only applied to a week with no shifts yet, so nothing is doubled.
Like the other services, these never commit.
"""

from dataclasses import dataclass
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import models as db
from services.errors import ConflictError
from services.loading import load_restaurant
from services.shifts import Need, create_shift, shift_needs
from services.weeks import week_bounds


@dataclass(frozen=True)
class PlannedShift:
    weekday: int  # 0 = Monday
    start_time: time
    end_time: time
    label: str | None
    needs: tuple[Need, ...]


# Reading and applying plans

def week_shifts(session: Session, restaurant_id: int, week_start: date) -> list[db.Shift]:
    """Active shifts starting in the week, in order."""
    restaurant = load_restaurant(session, restaurant_id)
    period_start, period_end = week_bounds(week_start, ZoneInfo(restaurant.timezone))
    return list(session.scalars(
        select(db.Shift)
        .where(
            db.Shift.restaurant_id == restaurant_id,
            db.Shift.status == "active",
            db.Shift.starts_at >= period_start,
            db.Shift.starts_at < period_end,
        )
        .order_by(db.Shift.starts_at, db.Shift.id)
    ))


def week_plan(session: Session, restaurant_id: int, week_start: date) -> list[PlannedShift]:
    """The week's shifts as a plan: weekday, local times, name and needs."""
    tz = ZoneInfo(load_restaurant(session, restaurant_id).timezone)
    shifts = week_shifts(session, restaurant_id, week_start)
    needs = shift_needs(session, [s.id for s in shifts])
    plan = []
    for shift in shifts:
        starts, ends = shift.starts_at.astimezone(tz), shift.ends_at.astimezone(tz)
        plan.append(PlannedShift(
            weekday=starts.weekday(),
            start_time=starts.time().replace(tzinfo=None),
            end_time=ends.time().replace(tzinfo=None),
            label=shift.label,
            needs=tuple(needs[shift.id]),
        ))
    return plan


def apply_plan(
    session: Session,
    restaurant_id: int,
    week_start: date,
    plan: list[PlannedShift],
    source: str,
) -> list[db.Shift]:
    """Create the plan's shifts in an empty week. `source` names it in errors."""
    if week_start.weekday() != 0:
        raise ValueError("Planning weeks start on a Monday.")
    if not plan:
        raise ValueError(f"{source} has no shifts to copy.")
    if week_shifts(session, restaurant_id, week_start):
        raise ConflictError(
            "This week already has shifts. Remove them first, or add shifts one by one."
        )

    return [
        create_shift(
            session,
            restaurant_id,
            local_date=week_start + timedelta(days=planned.weekday),
            start_time=planned.start_time,
            end_time=planned.end_time,
            needs=list(planned.needs),
            label=planned.label,
        )
        for planned in plan
    ]


def copy_week(
    session: Session, restaurant_id: int, from_week: date, to_week: date
) -> list[db.Shift]:
    """Copy one week's shifts and their needs (not who works them) into an empty week."""
    if from_week == to_week:
        raise ValueError("Pick a different week to copy from.")
    plan = week_plan(session, restaurant_id, from_week)
    return apply_plan(
        session, restaurant_id, to_week, plan, f"The week of {from_week:%d %b %Y}"
    )


# Templates

def save_template(
    session: Session, restaurant_id: int, name: str, week_start: date
) -> db.ShiftTemplate:
    """Save a week's shifts as a template that other weeks can start from."""
    name = " ".join(name.split())
    if not name:
        raise ValueError("Give the template a name.")
    plan = week_plan(session, restaurant_id, week_start)
    if not plan:
        raise ValueError("That week has no shifts to save.")
    if session.scalar(select(db.ShiftTemplate.id).where(
        db.ShiftTemplate.restaurant_id == restaurant_id, db.ShiftTemplate.name == name,
    )):
        raise ConflictError(f'A template called "{name}" already exists.')

    template = db.ShiftTemplate(
        restaurant_id=restaurant_id, name=name, shifts=[_to_json(p) for p in plan],
    )
    session.add(template)
    session.flush()
    return template


def list_templates(session: Session, restaurant_id: int) -> list[db.ShiftTemplate]:
    load_restaurant(session, restaurant_id)
    return list(session.scalars(
        select(db.ShiftTemplate)
        .where(db.ShiftTemplate.restaurant_id == restaurant_id)
        .order_by(db.ShiftTemplate.name)
    ))


def apply_template(
    session: Session, restaurant_id: int, template_id: int, week_start: date
) -> list[db.Shift]:
    template = _template(session, restaurant_id, template_id)
    plan = [_from_json(item) for item in template.shifts]
    return apply_plan(session, restaurant_id, week_start, plan, f'The template "{template.name}"')


def delete_template(session: Session, restaurant_id: int, template_id: int) -> None:
    session.delete(_template(session, restaurant_id, template_id))
    session.flush()


def _template(session: Session, restaurant_id: int, template_id: int) -> db.ShiftTemplate:
    template = session.get(db.ShiftTemplate, template_id)
    if template is None or template.restaurant_id != restaurant_id:
        raise LookupError(f"Template {template_id} not found.")
    return template


def _to_json(planned: PlannedShift) -> dict:
    return {
        "weekday": planned.weekday,
        "start_time": planned.start_time.strftime("%H:%M"),
        "end_time": planned.end_time.strftime("%H:%M"),
        "label": planned.label,
        "requirements": [
            {"role": n.role, "count": n.count, "min_count": n.min_count} for n in planned.needs
        ],
    }


def _from_json(item: dict) -> PlannedShift:
    return PlannedShift(
        weekday=item["weekday"],
        start_time=time.fromisoformat(item["start_time"]),
        end_time=time.fromisoformat(item["end_time"]),
        label=item["label"],
        needs=tuple(
            Need(r["role"], r["count"], r["min_count"]) for r in item["requirements"]
        ),
    )
