"""Call-out risk: what happens to the week if each scheduled person calls out.

For every assignment in the published schedule, simulate that person calling
out (off for the rest of the day, like a real call-out) and ask the engine for
the best repair. The result says, before anything goes wrong, which call-outs
the restaurant can absorb and which would leave it short.

Each simulation is an independent repair, so they run in parallel threads.
OR-Tools releases Python's GIL while solving, so threads use every CPU core.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from optimizer import engine
from optimizer.models import ScheduleResult
from services.callouts import exclusions_for_callouts, merge_exclusions
from services.explanations import CalloutExplanation, explain_exclusions
from services.loading import WeekInputs, load_restaurant, load_week
from services.scheduling import current_published, full_original_schedule, week_callouts
from services.weeks import week_bounds

RiskLevel = Literal["covered", "short", "no_fix"]


@dataclass(frozen=True)
class CalloutRisk:
    """The outcome if one person calls out of one shift."""

    shift_id: int
    employee_id: int
    role: str
    level: RiskLevel
    extra_missing: int | None  # positions left unfilled; None when no repair exists
    changes: int | None        # changes the repair needs; None when no repair exists
    why: CalloutExplanation | None = None  # why no repair exists (no_fix only)


@dataclass(frozen=True)
class RiskReport:
    schedule_id: int
    baseline_missing: int  # positions already short before any new call-out
    risks: list[CalloutRisk]
    week_fixable: bool = True  # False: recorded call-outs already can't be repaired
    blocker: CalloutExplanation | None = None  # why, when week_fixable is False

    @property
    def at_risk(self) -> list[CalloutRisk]:
        return [risk for risk in self.risks if risk.level != "covered"]


def _missing(result: ScheduleResult) -> int:
    return sum(shortage.missing for shortage in result.shortages)


def _repair(inputs: WeekInputs, original, excluded) -> ScheduleResult:
    return engine.repair(
        employees=inputs.employees,
        shifts=inputs.shifts,
        policy=inputs.policy,
        original_schedule=original,
        outside_assignments=inputs.outside_assignments,
        excluded_assignments=excluded or None,
        scheduling_timezone=inputs.timezone,
        deterministic=True,
    )


def callout_risk(
    session: Session,
    restaurant_id: int,
    week_start: date,
    max_workers: int | None = None,
) -> RiskReport:
    """Simulate a call-out for every assignment in the week's published schedule.

    Call-outs already recorded for the week are taken into account, and people
    already called out of a shift are skipped. Nothing is saved.
    """
    restaurant = load_restaurant(session, restaurant_id)
    period_start, period_end = week_bounds(week_start, ZoneInfo(restaurant.timezone))
    inputs = load_week(session, restaurant_id, period_start, period_end)

    published = current_published(session, restaurant_id, period_start)
    if published is None:
        raise LookupError("There is no published schedule for that week to check.")

    original = full_original_schedule(session, published.id, inputs)
    recorded = exclusions_for_callouts(
        week_callouts(session, inputs), inputs.shifts, inputs.timezone
    )
    shifts_by_id = {shift.id: shift for shift in inputs.shifts}

    candidates = [
        (shift_id, role, employee_id)
        for shift_id, roles in sorted(original.items())
        for role, employee_ids in roles.items()
        for employee_id in sorted(employee_ids)
        if employee_id not in recorded.get(shift_id, [])
    ]

    def excluded_with(candidate):
        shift_id, _, employee_id = candidate
        simulated = exclusions_for_callouts(
            [(employee_id, shifts_by_id[shift_id], True)], inputs.shifts, inputs.timezone
        )
        return merge_exclusions(recorded, simulated)

    def simulate(candidate) -> ScheduleResult:
        return _repair(inputs, original, excluded_with(candidate))

    # If the call-outs already recorded can't be repaired, every simulation
    # would fail too and the report would mark everyone. Say so instead.
    baseline = _repair(inputs, original, recorded)
    if baseline.assignments is None:
        return RiskReport(
            schedule_id=published.id,
            baseline_missing=0,
            risks=[],
            week_fixable=False,
            blocker=explain_exclusions(inputs, original, recorded),
        )
    baseline_missing = _missing(baseline)

    workers = max_workers or min(8, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(simulate, candidates))

    risks = []
    for (shift_id, role, employee_id), result in zip(candidates, results):
        if result.assignments is None:
            why = explain_exclusions(
                inputs, original, excluded_with((shift_id, role, employee_id))
            )
            risks.append(CalloutRisk(shift_id, employee_id, role, "no_fix", None, None, why))
            continue
        extra = max(0, _missing(result) - baseline_missing)
        risks.append(CalloutRisk(
            shift_id,
            employee_id,
            role,
            "short" if extra else "covered",
            extra,
            result.assignment_changes,
        ))

    return RiskReport(schedule_id=published.id, baseline_missing=baseline_missing, risks=risks)
