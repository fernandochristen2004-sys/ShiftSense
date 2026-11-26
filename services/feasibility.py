"""Plain reasons a week can't be scheduled.

When the solver says INFEASIBLE it doesn't say why. This finds the most
common cause, cheaply: a shift role that must be filled (its minimum) but
has too few people who hold the role, are available for the whole shift,
and haven't called out.

It's a quick first check, not a proof. A week can pass it and still be
impossible (max hours, rest between shifts, one person needed in two places
at once); the dashboard then falls back to a general message.
"""

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from optimizer.timeutils import employee_is_available
from services.callouts import exclusions_for_callouts
from services.loading import load_restaurant, load_week
from services.scheduling import week_callouts
from services.weeks import week_bounds


@dataclass(frozen=True)
class Blocker:
    shift_id: int
    role: str
    needed: int     # the shift's minimum for this role
    available: int  # people who could work it at all


def week_blockers(
    session: Session,
    restaurant_id: int,
    week_start: date,
    include_callouts: bool = True,
) -> list[Blocker]:
    """Shift roles that can't reach their minimum, in shift order."""
    restaurant = load_restaurant(session, restaurant_id)
    period_start, period_end = week_bounds(week_start, ZoneInfo(restaurant.timezone))
    inputs = load_week(session, restaurant_id, period_start, period_end)

    excluded: dict[int, list[int]] = {}
    if include_callouts:
        excluded = exclusions_for_callouts(
            week_callouts(session, inputs), inputs.shifts, inputs.timezone
        )

    blockers = []
    for shift in sorted(inputs.shifts, key=lambda s: (s.starts_at, s.id)):
        off = set(excluded.get(shift.id, ()))
        for requirement in shift.requirements:
            needed = requirement.count if requirement.min_count is None else requirement.min_count
            if needed == 0:
                continue
            available = sum(
                1
                for employee in inputs.employees
                if requirement.skill in employee.skills
                and employee.id not in off
                and employee_is_available(employee, shift, inputs.timezone)
            )
            if available < needed:
                blockers.append(Blocker(shift.id, requirement.skill, needed, available))
    return blockers
