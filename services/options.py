"""Ranked replacements: several ways to cover a call-out, best first.

The plain repair returns one answer. Managers often want a choice: "Wen
covers it with 2 changes, or Lina covers it but Kasun has to move". So for
the slot a call-out empties, try each person who has the skill: lock them
into the slot and run a full repair. Every option is a complete, valid
schedule. Options are ranked by

    1. positions left short   (fewest first)
    2. changes to the week    (fewest first)
    3. fairness               (hours closest to everyone's targets first)
    4. the cover's workload   (most room under their max hours first)

and a "leave it empty" option is included when that ranks among the best.
Nothing is saved: the chosen option is saved by `repair_published(cover=...)`,
which runs the same deterministic repair with the same lock.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from optimizer import engine
from optimizer.explain import explain_gaps
from optimizer.models import ScheduleResult
from optimizer.timeutils import shift_duration_minutes
from services.callouts import exclusions_for_callouts
from services.explanations import CalloutExplanation, explain_exclusions
from services.loading import WeekInputs, load_restaurant, load_week
from services.scheduling import current_published, full_original_schedule, week_callouts
from services.weeks import week_bounds

Assignments = dict[int, dict[str, list[int]]]


@dataclass(frozen=True)
class Cover:
    """Lock this person into this slot."""

    shift_id: int
    role: str
    employee_id: int


@dataclass(frozen=True)
class RepairOption:
    cover: Cover | None          # None: the slot is left empty
    result: ScheduleResult       # a complete, valid repair
    missing: int                 # positions short across the week
    changes: int                 # assignments changed from the published week
    fairness_minutes: int        # total distance from hour targets (lower is fairer)
    cover_minutes: int | None    # the cover's hours this week, after the repair
    cover_max_hours: int | None
    cover_same_day: tuple[int, ...]  # the cover's other shifts that day

    def rank_key(self) -> tuple:
        load = (
            self.cover_minutes / (self.cover_max_hours * 60)
            if self.cover_minutes is not None and self.cover_max_hours
            else 0.0
        )
        return (self.missing, self.changes, self.fairness_minutes, load)


@dataclass(frozen=True)
class OptionsReport:
    shift_id: int
    role: str
    options: list[RepairOption]               # best first; empty when nothing works
    why: CalloutExplanation | None = None     # when nobody can fill the slot


def _repair(inputs: WeekInputs, original: Assignments, excluded, cover: Cover | None):
    return engine.repair(
        employees=inputs.employees,
        shifts=inputs.shifts,
        policy=inputs.policy,
        original_schedule=original,
        outside_assignments=inputs.outside_assignments,
        locked_assignments=(
            {cover.shift_id: {cover.role: [cover.employee_id]}} if cover else None
        ),
        excluded_assignments=excluded or None,
        scheduling_timezone=inputs.timezone,
        deterministic=True,
    )


def _option(inputs: WeekInputs, cover: Cover | None, result: ScheduleResult) -> RepairOption:
    shifts = {shift.id: shift for shift in inputs.shifts}
    metrics = result.objective_values or {}
    cover_minutes = cover_max = None
    same_day: tuple[int, ...] = ()
    if cover is not None:
        worked = [
            shifts[shift_id]
            for shift_id, roles in result.assignments.items()
            for ids in roles.values()
            if cover.employee_id in ids
        ]
        cover_minutes = sum(shift_duration_minutes(shift) for shift in worked)
        cover_max = next(e.max_hours for e in inputs.employees if e.id == cover.employee_id)
        day = shifts[cover.shift_id].starts_at.astimezone(inputs.timezone).date()
        same_day = tuple(sorted(
            shift.id for shift in worked
            if shift.id != cover.shift_id
            and shift.starts_at.astimezone(inputs.timezone).date() == day
        ))
    return RepairOption(
        cover=cover,
        result=result,
        missing=sum(shortage.missing for shortage in result.shortages),
        changes=result.assignment_changes or 0,
        fairness_minutes=metrics.get("target_deviation_min", 0),
        cover_minutes=cover_minutes,
        cover_max_hours=cover_max,
        cover_same_day=same_day,
    )


def _fingerprint(assignments: Assignments) -> frozenset:
    return frozenset(
        (shift_id, role, employee_id)
        for shift_id, roles in assignments.items()
        for role, ids in roles.items()
        for employee_id in ids
    )


def repair_options(
    session: Session,
    restaurant_id: int,
    week_start: date,
    shift_id: int,
    employee_id: int,
    limit: int = 3,
    max_workers: int | None = None,
) -> OptionsReport:
    """Ways to cover a recorded call-out, best first.

    `shift_id` and `employee_id` name the call-out (already recorded). Every
    call-out recorded for the week is respected; the options differ in who
    fills the slot this one leaves.
    """
    restaurant = load_restaurant(session, restaurant_id)
    period_start, period_end = week_bounds(week_start, ZoneInfo(restaurant.timezone))
    inputs = load_week(session, restaurant_id, period_start, period_end)

    published = current_published(session, restaurant_id, period_start)
    if published is None:
        raise LookupError("There is no published schedule for that week to repair.")
    original = full_original_schedule(session, published.id, inputs)

    role = next(
        (r for r, ids in original.get(shift_id, {}).items() if employee_id in ids), None
    )
    if role is None:
        raise ValueError(
            f"Employee {employee_id} is not on shift {shift_id} in the published schedule."
        )

    excluded = exclusions_for_callouts(
        week_callouts(session, inputs), inputs.shifts, inputs.timezone
    )
    if employee_id not in excluded.get(shift_id, []):
        raise ValueError("Record the call-out first, then ask for options.")

    # Everyone with the skill who isn't plainly unavailable or called out.
    explanation = explain_gaps(
        inputs.employees, inputs.shifts, inputs.policy, original,
        {shift_id: [employee_id]}, inputs.timezone, inputs.outside_assignments,
    )
    gap = next(g for g in explanation.gaps if g.shift_id == shift_id and g.role == role)
    already_there = set(original[shift_id][role])
    covers = [
        Cover(shift_id, role, candidate.employee_id)
        for candidate in gap.candidates
        if candidate.reason not in ("unavailable", "called_out")
        and candidate.employee_id not in excluded.get(shift_id, [])
        # Already in this slot: not a replacement (a different role on the
        # same shift is fine; they can switch).
        and candidate.employee_id not in already_there
    ]

    attempts: list[Cover | None] = [None, *covers]
    workers = max_workers or min(8, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda c: _repair(inputs, original, excluded, c), attempts))

    options: dict[frozenset, RepairOption] = {}
    for cover, result in zip(attempts, results):
        if result.assignments is None:
            continue
        # Name the cover from who actually ends up in the slot, never from
        # the lock alone, so a card can't credit the wrong person.
        filled = set(result.assignments.get(shift_id, {}).get(role, []))
        newcomers = filled - already_there
        if cover is None:
            cover = Cover(shift_id, role, min(newcomers)) if newcomers else None
        elif cover.employee_id not in newcomers:
            continue
        option = _option(inputs, cover, result)
        key = _fingerprint(result.assignments)
        if key not in options or option.rank_key() < options[key].rank_key():
            options[key] = option

    ranked = sorted(
        options.values(),
        key=lambda o: (*o.rank_key(), o.cover is None, o.cover.employee_id if o.cover else 0),
    )

    # One option per cover: the best way to use each person.
    seen: set[int | None] = set()
    best = []
    for option in ranked:
        who = option.cover.employee_id if option.cover else None
        if who not in seen:
            seen.add(who)
            best.append(option)

    # Nobody can fill the slot (no options, or only "leave it empty"): say why.
    why = None
    if not any(option.cover for option in best):
        why = explain_exclusions(inputs, original, excluded)
    return OptionsReport(shift_id=shift_id, role=role, options=best[:limit], why=why)
