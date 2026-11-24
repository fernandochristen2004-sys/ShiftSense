"""Scheduling workflows backed by the database."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import models as db
from optimizer import engine
from optimizer.models import ScheduleResult
from services.loading import WeekInputs, load_restaurant, load_week
from services.weeks import week_bounds
from zoneinfo import ZoneInfo


class EngineValidationError(RuntimeError):
    """The engine returned a schedule that broke a rule. This is a bug."""


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
