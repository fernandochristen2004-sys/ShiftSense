"""Load a restaurant's planning week from the database as engine inputs."""

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import models as db
from optimizer.models import (
    AvailabilityException,
    DateTimeShift,
    Employee,
    FixedAssignment,
    SchedulingPolicy,
    ShiftRequirement,
    WeeklyAvailability,
)

# Outside assignments closer than this to the week can affect rest rules.
OUTSIDE_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class WeekInputs:
    """Everything the engine needs to schedule one restaurant week."""

    restaurant_id: int
    timezone: tzinfo
    period_start: datetime
    period_end: datetime
    employees: list[Employee]
    shifts: list[DateTimeShift]
    policy: SchedulingPolicy
    outside_assignments: tuple[FixedAssignment, ...]
    skill_ids: dict[str, int]  # role name -> skills.id, for saving results


def load_restaurant(session: Session, restaurant_id: int) -> db.Restaurant:
    restaurant = session.get(db.Restaurant, restaurant_id)
    if restaurant is None:
        raise LookupError(f"Restaurant {restaurant_id} not found.")
    return restaurant


def load_policy(session: Session, restaurant_id: int) -> SchedulingPolicy:
    """The restaurant's policy, or the engine's defaults if none is saved."""
    row = session.get(db.SchedulingPolicy, restaurant_id)
    if row is None:
        return SchedulingPolicy()
    return SchedulingPolicy(
        minimum_rest_hours=row.minimum_rest_minutes // 60,
        enforce_minimum_rest=row.enforce_minimum_rest,
        fairness_enabled=row.fairness_enabled,
        allow_split_shifts=row.allow_split_shifts,
        split_shift_min_break_minutes=row.split_shift_min_break_minutes,
        max_split_span_minutes=row.max_split_span_minutes,
        allow_partial_coverage=row.allow_partial_coverage,
    )


def load_employees(session: Session, restaurant_id: int) -> list[Employee]:
    """Active employees with skills, weekly rules and date exceptions."""
    rows = session.scalars(
        select(db.Employee)
        .where(db.Employee.restaurant_id == restaurant_id, db.Employee.status == "active")
        .order_by(db.Employee.id)
    ).all()
    ids = [row.id for row in rows]

    skills: dict[int, set[str]] = {i: set() for i in ids}
    for employee_id, name in session.execute(
        select(db.EmployeeSkill.employee_id, db.Skill.name)
        .join(db.Skill, db.Skill.id == db.EmployeeSkill.skill_id)
        .where(db.EmployeeSkill.employee_id.in_(ids))
    ):
        skills[employee_id].add(name)

    weekly: dict[int, list[WeeklyAvailability]] = {i: [] for i in ids}
    for rule in session.scalars(
        select(db.AvailabilityRule)
        .where(db.AvailabilityRule.employee_id.in_(ids))
        .order_by(db.AvailabilityRule.id)
    ):
        weekly[rule.employee_id].append(
            WeeklyAvailability(rule.weekday, rule.start_time, rule.end_time)
        )

    intervals: dict[int, list] = {}
    for interval in session.scalars(
        select(db.AvailabilityExceptionInterval)
        .join(
            db.AvailabilityException,
            db.AvailabilityException.id == db.AvailabilityExceptionInterval.exception_id,
        )
        .where(db.AvailabilityException.employee_id.in_(ids))
        .order_by(db.AvailabilityExceptionInterval.start_time)
    ):
        intervals.setdefault(interval.exception_id, []).append(
            (interval.start_time, interval.end_time)
        )

    exceptions: dict[int, list[AvailabilityException]] = {i: [] for i in ids}
    for row in session.scalars(
        select(db.AvailabilityException)
        .where(db.AvailabilityException.employee_id.in_(ids))
        .order_by(db.AvailabilityException.local_date)
    ):
        exceptions[row.employee_id].append(
            AvailabilityException(
                date=row.local_date,
                available=row.available,
                intervals=tuple(intervals.get(row.id, ())) if row.available else (),
            )
        )

    return [
        Employee(
            id=row.id,
            name=row.display_name,
            skills=frozenset(skills[row.id]),
            max_hours=row.max_minutes // 60,  # whole hours only (database check)
            target_minutes=row.target_minutes,
            weekly_availability=tuple(weekly[row.id]),
            availability_exceptions=tuple(exceptions[row.id]),
        )
        for row in rows
    ]


def load_shifts(
    session: Session,
    restaurant_id: int,
    period_start: datetime,
    period_end: datetime,
) -> list[DateTimeShift]:
    """Active shifts that start inside the planning week, with requirements."""
    rows = session.scalars(
        select(db.Shift)
        .where(
            db.Shift.restaurant_id == restaurant_id,
            db.Shift.status == "active",
            db.Shift.starts_at >= period_start,
            db.Shift.starts_at < period_end,
        )
        .order_by(db.Shift.starts_at, db.Shift.id)
    ).all()
    return _with_requirements(session, rows)


def _with_requirements(session: Session, rows) -> list[DateTimeShift]:
    ids = [row.id for row in rows]
    requirements: dict[int, list[ShiftRequirement]] = {i: [] for i in ids}
    for shift_id, name, count, min_count in session.execute(
        select(
            db.ShiftRequirement.shift_id,
            db.Skill.name,
            db.ShiftRequirement.count,
            db.ShiftRequirement.min_count,
        )
        .join(db.Skill, db.Skill.id == db.ShiftRequirement.skill_id)
        .where(db.ShiftRequirement.shift_id.in_(ids))
        .order_by(db.ShiftRequirement.id)
    ):
        requirements[shift_id].append(ShiftRequirement(name, count, min_count))

    shifts = []
    for row in rows:
        if not requirements[row.id]:
            label = f" ({row.label})" if row.label else ""
            raise ValueError(f"Shift {row.id}{label} has no staffing requirements.")
        shifts.append(
            DateTimeShift(
                id=row.id,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                requirements=tuple(requirements[row.id]),
            )
        )
    return shifts


def load_outside_assignments(
    session: Session,
    restaurant_id: int,
    period_start: datetime,
    period_end: datetime,
) -> tuple[FixedAssignment, ...]:
    """Published work just before and after the week, for rest rules."""
    rows = session.execute(
        select(db.Assignment.employee_id, db.Shift)
        .join(db.Schedule, db.Schedule.id == db.Assignment.schedule_id)
        .join(db.Shift, db.Shift.id == db.Assignment.shift_id)
        .where(
            db.Assignment.restaurant_id == restaurant_id,
            db.Schedule.status == "published",
            db.Shift.status == "active",
            db.Shift.ends_at > period_start - OUTSIDE_WINDOW,
            db.Shift.starts_at < period_end + OUTSIDE_WINDOW,
            # Outside the week: started before it, or starts after it.
            (db.Shift.starts_at < period_start) | (db.Shift.starts_at >= period_end),
        )
        .order_by(db.Shift.starts_at, db.Assignment.employee_id)
    ).all()

    shifts = {
        shift.id: shift
        for shift in _with_requirements(session, sorted({row[1] for row in rows}, key=lambda s: s.id))
    }
    return tuple(
        FixedAssignment(employee_id=employee_id, shift=shifts[shift.id])
        for employee_id, shift in rows
    )


def load_week(
    session: Session,
    restaurant_id: int,
    period_start: datetime,
    period_end: datetime,
) -> WeekInputs:
    """Load everything the engine needs for one restaurant week."""
    restaurant = load_restaurant(session, restaurant_id)

    skill_ids = dict(
        session.execute(
            select(db.Skill.name, db.Skill.id).where(db.Skill.restaurant_id == restaurant_id)
        ).all()
    )

    return WeekInputs(
        restaurant_id=restaurant_id,
        timezone=ZoneInfo(restaurant.timezone),
        period_start=period_start,
        period_end=period_end,
        employees=load_employees(session, restaurant_id),
        shifts=load_shifts(session, restaurant_id, period_start, period_end),
        policy=load_policy(session, restaurant_id),
        outside_assignments=load_outside_assignments(
            session, restaurant_id, period_start, period_end
        ),
        skill_ids=skill_ids,
    )
