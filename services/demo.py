"""Fill the database with a synthetic demo restaurant.

Used by tests, and later by a "load demo restaurant" button. The synthetic
generator produces exact UTC availability for one week; here it is stored the
way real restaurants store it, as weekly rules in the restaurant's timezone
(UTC for demo restaurants, so the times match exactly).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from db import models as db
from optimizer.demo import demo_name
from optimizer.synthetic_data import generate_restaurant_scenario

DEMO_TIMEZONE = "UTC"


@dataclass(frozen=True)
class DemoRestaurant:
    restaurant_id: int
    week_start: date
    employee_ids: dict[int, int]  # synthetic employee id -> database id
    shift_ids: dict[int, int]     # synthetic shift id -> database id


def seed_demo_restaurant(
    session: Session,
    employee_count: int = 25,
    seed: int = 42,
    week_start: date = date(2026, 11, 23),
    name: str = "Demo Bistro",
) -> DemoRestaurant:
    """Store a synthetic restaurant: staff, skills, availability, shifts, policy."""
    if week_start.weekday() != 0:
        raise ValueError("Demo weeks start on a Monday.")

    scenario = generate_restaurant_scenario(employee_count, seed=seed, start_date=week_start)

    restaurant = db.Restaurant(name=name, timezone=DEMO_TIMEZONE)
    session.add(restaurant)
    session.flush()

    policy = scenario.policy
    session.add(db.SchedulingPolicy(
        restaurant_id=restaurant.id,
        minimum_rest_minutes=policy.minimum_rest_hours * 60,
        enforce_minimum_rest=policy.enforce_minimum_rest,
        allow_split_shifts=policy.allow_split_shifts,
        split_shift_min_break_minutes=policy.split_shift_min_break_minutes,
        max_split_span_minutes=policy.max_split_span_minutes,
        fairness_enabled=policy.fairness_enabled,
        allow_partial_coverage=policy.allow_partial_coverage,
    ))

    skill_names = sorted(
        {skill for e in scenario.employees for skill in e.skills}
        | {r.skill for s in scenario.shifts for r in s.requirements}
    )
    skills = {name: db.Skill(restaurant_id=restaurant.id, name=name) for name in skill_names}
    session.add_all(skills.values())
    session.flush()

    employee_ids = {}
    for synthetic in sorted(scenario.employees, key=lambda e: e.id):
        employee = db.Employee(
            restaurant_id=restaurant.id,
            display_name=demo_name(synthetic.id),
            max_minutes=synthetic.max_hours * 60,
            target_minutes=synthetic.target_minutes,
        )
        session.add(employee)
        session.flush()
        employee_ids[synthetic.id] = employee.id

        session.add_all(
            db.EmployeeSkill(
                restaurant_id=restaurant.id,
                employee_id=employee.id,
                skill_id=skills[name].id,
            )
            for name in sorted(synthetic.skills)
        )
        # Each synthetic interval is one day's window, possibly past midnight.
        session.add_all(
            db.AvailabilityRule(
                employee_id=employee.id,
                weekday=start.weekday(),
                start_time=start.time(),
                end_time=end.time(),
            )
            for start, end in synthetic.datetime_availability
            if end - start < timedelta(hours=24)
        )

    shift_ids = {}
    for synthetic in sorted(scenario.shifts, key=lambda s: s.id):
        shift = db.Shift(
            restaurant_id=restaurant.id,
            starts_at=synthetic.starts_at,
            ends_at=synthetic.ends_at,
        )
        session.add(shift)
        session.flush()
        shift_ids[synthetic.id] = shift.id

        session.add_all(
            db.ShiftRequirement(
                restaurant_id=restaurant.id,
                shift_id=shift.id,
                skill_id=skills[r.skill].id,
                count=r.count,
                min_count=r.effective_min_count,
            )
            for r in synthetic.requirements
        )

    session.flush()
    return DemoRestaurant(
        restaurant_id=restaurant.id,
        week_start=week_start,
        employee_ids=employee_ids,
        shift_ids=shift_ids,
    )
