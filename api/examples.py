"""Example API requests built from synthetic restaurants.

Used by tests, and later by a "load demo restaurant" feature.
"""

from optimizer.synthetic_data import RestaurantScenario


def scenario_request(scenario: RestaurantScenario, deterministic: bool = False) -> dict:
    """Convert a synthetic restaurant into a /schedules/generate request body."""
    policy = scenario.policy
    return {
        "employees": [
            {
                "id": e.id,
                "name": e.name,
                "skills": sorted(e.skills),
                "max_hours": e.max_hours,
                "target_minutes": e.target_minutes,
                "datetime_availability": [
                    {"starts_at": start.isoformat(), "ends_at": end.isoformat()}
                    for start, end in e.datetime_availability
                ],
            }
            for e in scenario.employees
        ],
        "shifts": [
            {
                "id": s.id,
                "starts_at": s.starts_at.isoformat(),
                "ends_at": s.ends_at.isoformat(),
                "requirements": [
                    {"skill": r.skill, "count": r.count, "min_count": r.min_count}
                    for r in s.requirements
                ],
            }
            for s in scenario.shifts
        ],
        "policy": {
            "minimum_rest_hours": policy.minimum_rest_hours,
            "enforce_minimum_rest": policy.enforce_minimum_rest,
            "fairness_enabled": policy.fairness_enabled,
            "allow_split_shifts": policy.allow_split_shifts,
            "split_shift_min_break_minutes": policy.split_shift_min_break_minutes,
            "max_split_span_minutes": policy.max_split_span_minutes,
            "allow_partial_coverage": policy.allow_partial_coverage,
        },
        "deterministic": deterministic,
    }
