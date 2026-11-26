"""Why call-outs can't be covered: structured reasons plus a one-line summary.

The reasoning lives in optimizer/explain.py; this module loads the week and
packages the result for the API.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from optimizer.explain import Explanation, explain_gaps, summarize
from services.callouts import exclusions_for_callouts
from services.loading import WeekInputs, load_restaurant, load_week
from services.scheduling import current_published, full_original_schedule, week_callouts
from services.weeks import week_bounds


@dataclass(frozen=True)
class CalloutExplanation:
    explanation: Explanation
    summary: str  # one plain sentence per blocking gap


def explain_exclusions(
    inputs: WeekInputs,
    original: Mapping[int, Mapping[str, Iterable[int]]],
    excluded: Mapping[int, Iterable[int]],
) -> CalloutExplanation:
    """Why the gaps these exclusions leave can't be filled."""
    explanation = explain_gaps(
        inputs.employees,
        inputs.shifts,
        inputs.policy,
        original,
        excluded,
        inputs.timezone,
        inputs.outside_assignments,
    )
    names = {employee.id: employee.name for employee in inputs.employees}
    return CalloutExplanation(
        explanation, summarize(explanation, inputs.shifts, inputs.timezone, names)
    )


def explain_recorded_callouts(
    session: Session, restaurant_id: int, week_start: date
) -> CalloutExplanation | None:
    """Why the week's recorded call-outs can't all be covered.

    None when nothing is published or no call-outs are recorded.
    """
    restaurant = load_restaurant(session, restaurant_id)
    period_start, period_end = week_bounds(week_start, ZoneInfo(restaurant.timezone))
    published = current_published(session, restaurant_id, period_start)
    if published is None:
        return None
    inputs = load_week(session, restaurant_id, period_start, period_end)
    recorded = exclusions_for_callouts(
        week_callouts(session, inputs), inputs.shifts, inputs.timezone
    )
    if not recorded:
        return None
    original = full_original_schedule(session, published.id, inputs)
    return explain_exclusions(inputs, original, recorded)
