"""Scheduling workflows backed by the database.

Every function changes the session but never commits: the caller (an API
request, a script, a test) decides when the whole unit of work is saved.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import models as db
from optimizer import engine
from optimizer.models import ScheduleResult
from services.callouts import exclusions_for_callouts
from services.loading import WeekInputs, load_restaurant, load_week
from services.weeks import week_bounds


class EngineValidationError(RuntimeError):
    """The engine returned a schedule that broke a rule. This is a bug."""


class StaleScheduleError(RuntimeError):
    """The schedule changed since it was loaded, or its base is no longer published."""


class ShortagesNotAcceptedError(ValueError):
    """Publishing a schedule with shortages needs the manager's confirmation."""


@dataclass(frozen=True)
class DraftOutcome:
    """The engine's result and, if a schedule was found, the saved draft."""

    result: ScheduleResult
    schedule: db.Schedule | None


def next_revision_number(session: Session, inputs: WeekInputs) -> int:
    latest = session.scalar(
        select(func.max(db.Schedule.revision_number)).where(
            db.Schedule.restaurant_id == inputs.restaurant_id,
            db.Schedule.period_start == inputs.period_start,
        )
    )
    return (latest or 0) + 1


def save_revision(
    session: Session,
    inputs: WeekInputs,
    result: ScheduleResult,
    based_on: db.Schedule | None = None,
) -> db.Schedule:
    """Save an engine result as a new draft revision with its assignments."""
    if result.assignments is None:
        raise ValueError("There is no schedule to save.")
    if result.validation_errors:
        raise EngineValidationError(
            "The engine returned a schedule that breaks a rule: "
            + "; ".join(result.validation_errors)
        )

    schedule = db.Schedule(
        restaurant_id=inputs.restaurant_id,
        period_start=inputs.period_start,
        period_end=inputs.period_end,
        revision_number=next_revision_number(session, inputs),
        based_on_id=based_on.id if based_on else None,
        status="draft",
        solver_status=result.status,
        fully_covered=result.fully_covered,
        shortages=[
            {"shift_id": s.shift_id, "role": s.role, "missing": s.missing}
            for s in result.shortages
        ],
        objective_values=dict(result.objective_values or {}),
        schedule_metrics=dict(result.schedule_metrics or {}),
        assignment_changes=result.assignment_changes,
    )
    session.add(schedule)
    session.flush()

    session.add_all(
        db.Assignment(
            restaurant_id=inputs.restaurant_id,
            schedule_id=schedule.id,
            shift_id=shift_id,
            employee_id=employee_id,
            skill_id=inputs.skill_ids[role],
        )
        for shift_id, roles in sorted(result.assignments.items())
        for role, employee_ids in roles.items()
        for employee_id in sorted(employee_ids)
    )
    session.flush()
    return schedule


def generate_draft(
    session: Session,
    restaurant_id: int,
    week_start: date,
    deterministic: bool = False,
) -> DraftOutcome:
    """Build a new draft schedule for one week from the stored restaurant data.

    The draft is saved as the next revision for that week. If no schedule is
    possible, nothing is saved and the engine's result explains why.
    The caller decides when to commit.
    """
    restaurant = load_restaurant(session, restaurant_id)
    period_start, period_end = week_bounds(week_start, ZoneInfo(restaurant.timezone))
    inputs = load_week(session, restaurant_id, period_start, period_end)

    result = engine.generate(
        employees=inputs.employees,
        shifts=inputs.shifts,
        policy=inputs.policy,
        outside_assignments=inputs.outside_assignments,
        scheduling_timezone=inputs.timezone,
        deterministic=deterministic,
    )

    if result.assignments is None:
        return DraftOutcome(result=result, schedule=None)

    return DraftOutcome(result=result, schedule=save_revision(session, inputs, result))


def schedule_assignments(
    session: Session,
    schedule_id: int,
) -> dict[int, dict[str, list[int]]]:
    """A saved revision's assignments in the engine's format."""
    schedule: dict[int, dict[str, list[int]]] = {}
    for shift_id, role, employee_id in session.execute(
        select(db.Assignment.shift_id, db.Skill.name, db.Assignment.employee_id)
        .join(db.Skill, db.Skill.id == db.Assignment.skill_id)
        .where(db.Assignment.schedule_id == schedule_id)
        .order_by(db.Assignment.shift_id, db.Assignment.employee_id)
    ):
        schedule.setdefault(shift_id, {}).setdefault(role, []).append(employee_id)
    return schedule


# Publishing

def current_published(
    session: Session,
    restaurant_id: int,
    period_start: datetime,
) -> db.Schedule | None:
    return session.scalars(
        select(db.Schedule).where(
            db.Schedule.restaurant_id == restaurant_id,
            db.Schedule.period_start == period_start,
            db.Schedule.status == "published",
        )
    ).one_or_none()


def publish_schedule(
    session: Session,
    schedule_id: int,
    expected_row_version: int,
    accept_shortages: bool = False,
    now: datetime | None = None,
) -> db.Schedule:
    """Publish a draft and archive the week's current published revision.

    Both happen in the caller's transaction, so the week is never left with
    zero or two published revisions.

    `expected_row_version` is the version the manager was looking at. If the
    draft changed since then, publishing is refused.
    """
    schedule = session.get(db.Schedule, schedule_id)
    if schedule is None:
        raise LookupError(f"Schedule {schedule_id} not found.")
    if schedule.row_version != expected_row_version:
        raise StaleScheduleError(
            f"Schedule {schedule_id} changed since you loaded it "
            f"(version {expected_row_version}, now {schedule.row_version}). Reload and try again."
        )
    if schedule.status != "draft":
        raise ValueError(f"Only drafts can be published; this one is {schedule.status}.")
    if schedule.solver_status not in ("OPTIMAL", "FEASIBLE"):
        raise ValueError("Only schedules the engine completed can be published.")

    missing = sum(shortage["missing"] for shortage in schedule.shortages)
    if missing and not accept_shortages:
        raise ShortagesNotAcceptedError(
            f"This schedule is {missing} position(s) short. "
            "Confirm to publish it anyway."
        )

    published = current_published(session, schedule.restaurant_id, schedule.period_start)

    if schedule.based_on_id is not None and (
        published is None or published.id != schedule.based_on_id
    ):
        raise StaleScheduleError(
            f"Revision {schedule.revision_number} was built from a revision that is "
            "no longer published. Repair the current schedule again."
        )

    if published is not None:
        published.status = "archived"
        session.flush()  # free the "one published per week" slot first

    schedule.status = "published"
    schedule.published_at = now or datetime.now(timezone.utc)
    session.flush()
    return schedule


# Call-outs

def record_absence(
    session: Session,
    restaurant_id: int,
    employee_id: int,
    shift_id: int,
    rest_of_day: bool = True,
    note: str | None = None,
) -> db.Absence:
    """Record that an employee can't work a shift they're published on."""
    shift = session.get(db.Shift, shift_id)
    if shift is None or shift.restaurant_id != restaurant_id:
        raise LookupError(f"Shift {shift_id} not found.")

    published = session.scalars(
        select(db.Schedule).where(
            db.Schedule.restaurant_id == restaurant_id,
            db.Schedule.status == "published",
            db.Schedule.period_start <= shift.starts_at,
            db.Schedule.period_end > shift.starts_at,
        )
    ).one_or_none()
    if published is None:
        raise ValueError("There is no published schedule for that shift's week.")

    scheduled = session.scalar(
        select(func.count()).where(
            db.Assignment.schedule_id == published.id,
            db.Assignment.shift_id == shift_id,
            db.Assignment.employee_id == employee_id,
        )
    )
    if not scheduled:
        raise ValueError(
            f"Employee {employee_id} is not on shift {shift_id} in the published "
            "schedule, so there is nothing to call out of."
        )

    absence = db.Absence(
        restaurant_id=restaurant_id,
        employee_id=employee_id,
        shift_id=shift_id,
        rest_of_day=rest_of_day,
        note=note,
    )
    try:
        with session.begin_nested():
            session.add(absence)
            session.flush()
    except IntegrityError:
        raise ValueError(
            f"A call-out for employee {employee_id} on shift {shift_id} is already recorded."
        ) from None
    return absence


def week_callouts(session: Session, inputs: WeekInputs):
    """Absences affecting the week, as (employee_id, shift, rest_of_day).

    Includes call-outs from the day before the week, since "rest of day"
    can reach past midnight into Monday morning.
    """
    rows = session.execute(
        select(db.Absence.employee_id, db.Shift, db.Absence.rest_of_day)
        .join(db.Shift, db.Shift.id == db.Absence.shift_id)
        .where(
            db.Absence.restaurant_id == inputs.restaurant_id,
            db.Shift.starts_at >= inputs.period_start - timedelta(days=1),
            db.Shift.starts_at < inputs.period_end,
        )
        .order_by(db.Absence.id)
    ).all()
    return [(employee_id, shift, rest_of_day) for employee_id, shift, rest_of_day in rows]


def full_original_schedule(
    session: Session,
    schedule_id: int,
    inputs: WeekInputs,
) -> dict[int, dict[str, list[int]]]:
    """A saved revision in the engine's repair format: every shift and role."""
    saved = schedule_assignments(session, schedule_id)
    return {
        shift.id: {
            requirement.skill: list(saved.get(shift.id, {}).get(requirement.skill, []))
            for requirement in shift.requirements
        }
        for shift in inputs.shifts
    }


def repair_published(
    session: Session,
    restaurant_id: int,
    week_start: date,
    deterministic: bool = False,
) -> DraftOutcome:
    """Repair the week's published schedule using every recorded call-out.

    The repair is saved as a new draft based on the published revision. The
    published revision stays in place until the repair is published.
    """
    restaurant = load_restaurant(session, restaurant_id)
    period_start, period_end = week_bounds(week_start, ZoneInfo(restaurant.timezone))
    inputs = load_week(session, restaurant_id, period_start, period_end)

    published = current_published(session, restaurant_id, period_start)
    if published is None:
        raise LookupError("There is no published schedule for that week to repair.")

    excluded = exclusions_for_callouts(
        week_callouts(session, inputs), inputs.shifts, inputs.timezone
    )

    result = engine.repair(
        employees=inputs.employees,
        shifts=inputs.shifts,
        policy=inputs.policy,
        original_schedule=full_original_schedule(session, published.id, inputs),
        outside_assignments=inputs.outside_assignments,
        excluded_assignments=excluded or None,
        scheduling_timezone=inputs.timezone,
        deterministic=deterministic,
    )

    if result.assignments is None:
        return DraftOutcome(result=result, schedule=None)

    return DraftOutcome(
        result=result,
        schedule=save_revision(session, inputs, result, based_on=published),
    )
