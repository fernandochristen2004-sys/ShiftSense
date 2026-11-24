"""Loading restaurant weeks from the database and saving draft schedules."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from db import models
from optimizer import engine
from optimizer.models import ScheduleResult
from optimizer.synthetic_data import generate_restaurant_scenario
from services.demo import seed_demo_restaurant
from services.loading import load_week
from services.scheduling import (
    EngineValidationError,
    generate_draft,
    save_revision,
    schedule_assignments,
)
from services.weeks import week_bounds

MONDAY = date(2026, 11, 23)
UTC = ZoneInfo("UTC")


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def _add(session, record):
    session.add(record)
    session.flush()
    return record


# Planning weeks

def test_week_bounds_are_monday_to_monday():
    start, end = week_bounds(MONDAY, ZoneInfo("Asia/Colombo"))

    assert start == datetime(2026, 11, 23, tzinfo=ZoneInfo("Asia/Colombo"))
    assert end - start == timedelta(days=7)


def test_week_must_start_on_monday():
    with pytest.raises(ValueError):
        week_bounds(date(2026, 11, 24), UTC)


def test_week_with_a_clock_change_is_one_local_week():
    # UK clocks go back on Sunday 25 October 2026, so that week lasts 169 hours.
    start, end = week_bounds(date(2026, 10, 19), ZoneInfo("Europe/London"))

    # Python subtracts same-timezone datetimes by wall clock, so compare in UTC.
    elapsed = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    assert elapsed == timedelta(days=7, hours=1)
    assert (start.hour, end.hour, end.weekday()) == (0, 0, 0)


# Demo restaurant

def test_demo_restaurant_is_stored(db):
    demo = seed_demo_restaurant(db, employee_count=25)

    assert _count(db, models.Employee) == 25
    assert _count(db, models.Shift) == 16
    assert db.get(models.SchedulingPolicy, demo.restaurant_id) is not None


# Loading

def test_loaded_week_matches_the_demo_restaurant(db):
    demo = seed_demo_restaurant(db, employee_count=25)
    scenario = generate_restaurant_scenario(25, seed=42, start_date=MONDAY)
    start, end = week_bounds(MONDAY, UTC)

    inputs = load_week(db, demo.restaurant_id, start, end)

    assert len(inputs.employees) == 25
    assert len(inputs.shifts) == 16
    assert inputs.policy == scenario.policy
    assert {e.name for e in inputs.employees} == {e.name for e in scenario.employees}
    assert sum(len(s.requirements) for s in inputs.shifts) == sum(
        len(s.requirements) for s in scenario.shifts
    )


def test_loaded_week_schedules_like_the_original_data(db):
    """Nothing is lost on the way through the database."""
    demo = seed_demo_restaurant(db, employee_count=25)
    scenario = generate_restaurant_scenario(25, seed=42, start_date=MONDAY)
    start, end = week_bounds(MONDAY, UTC)
    inputs = load_week(db, demo.restaurant_id, start, end)

    direct = engine.generate(
        employees=list(scenario.employees),
        shifts=list(scenario.shifts),
        policy=scenario.policy,
        deterministic=True,
    )
    from_database = engine.generate(
        employees=inputs.employees,
        shifts=inputs.shifts,
        policy=inputs.policy,
        scheduling_timezone=inputs.timezone,
        deterministic=True,
    )

    assert from_database.status == direct.status
    assert from_database.validation_errors == ()
    assert sum(s.missing for s in from_database.shortages) == sum(
        s.missing for s in direct.shortages
    )


def test_inactive_employees_and_cancelled_shifts_are_left_out(db):
    demo = seed_demo_restaurant(db, employee_count=25)
    first_employee = db.get(models.Employee, min(demo.employee_ids.values()))
    first_shift = db.get(models.Shift, min(demo.shift_ids.values()))
    first_employee.status = "inactive"
    first_shift.status = "cancelled"
    db.flush()

    inputs = load_week(db, demo.restaurant_id, *week_bounds(MONDAY, UTC))

    assert first_employee.id not in {e.id for e in inputs.employees}
    assert first_shift.id not in {s.id for s in inputs.shifts}


def test_date_exceptions_are_loaded(db):
    restaurant = _add(db, models.Restaurant(name="Lanka Bistro", timezone="Asia/Colombo"))
    employee = _add(db, models.Employee(
        restaurant_id=restaurant.id, display_name="Asha", max_minutes=2400,
    ))
    _add(db, models.AvailabilityRule(
        employee_id=employee.id, weekday=1, start_time=time(9), end_time=time(17),
    ))
    _add(db, models.AvailabilityException(
        employee_id=employee.id, local_date=date(2026, 11, 23), available=False,
    ))
    open_day = _add(db, models.AvailabilityException(
        employee_id=employee.id, local_date=date(2026, 11, 24), available=True,
    ))
    _add(db, models.AvailabilityExceptionInterval(
        exception_id=open_day.id, start_time=time(14), end_time=time(22),
    ))

    inputs = load_week(db, restaurant.id, *week_bounds(MONDAY, ZoneInfo("Asia/Colombo")))
    loaded = inputs.employees[0]

    assert [(r.weekday, r.start_time) for r in loaded.weekly_availability] == [(1, time(9))]
    assert [(x.date, x.available, x.intervals) for x in loaded.availability_exceptions] == [
        (date(2026, 11, 23), False, ()),
        (date(2026, 11, 24), True, ((time(14), time(22)),)),
    ]


def test_shift_without_requirements_is_reported(db):
    restaurant = _add(db, models.Restaurant(name="Lanka Bistro", timezone="UTC"))
    _add(db, models.Shift(
        restaurant_id=restaurant.id,
        label="Monday lunch",
        starts_at=datetime(2026, 11, 23, 11, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 23, 15, tzinfo=timezone.utc),
    ))

    with pytest.raises(ValueError, match="Monday lunch"):
        load_week(db, restaurant.id, *week_bounds(MONDAY, UTC))


def test_unknown_restaurant_is_reported(db):
    with pytest.raises(LookupError):
        load_week(db, 999_999, *week_bounds(MONDAY, UTC))


def test_published_work_next_to_the_week_is_loaded_for_rest_rules(db):
    restaurant = _add(db, models.Restaurant(name="Lanka Bistro", timezone="UTC"))
    employee = _add(db, models.Employee(
        restaurant_id=restaurant.id, display_name="Asha", max_minutes=2400,
    ))
    skill = _add(db, models.Skill(restaurant_id=restaurant.id, name="bartender"))
    sunday_close = _add(db, models.Shift(
        restaurant_id=restaurant.id,
        starts_at=datetime(2026, 11, 22, 23, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 23, 2, tzinfo=timezone.utc),
    ))
    _add(db, models.ShiftRequirement(
        restaurant_id=restaurant.id, shift_id=sunday_close.id, skill_id=skill.id, count=1, min_count=1,
    ))
    last_week = _add(db, models.Schedule(
        restaurant_id=restaurant.id,
        period_start=datetime(2026, 11, 16, tzinfo=timezone.utc),
        period_end=datetime(2026, 11, 23, tzinfo=timezone.utc),
        revision_number=1,
        status="published",
        published_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
    ))
    _add(db, models.Assignment(
        restaurant_id=restaurant.id,
        schedule_id=last_week.id,
        shift_id=sunday_close.id,
        employee_id=employee.id,
        skill_id=skill.id,
    ))

    inputs = load_week(db, restaurant.id, *week_bounds(MONDAY, UTC))

    assert [(a.employee_id, a.shift.id) for a in inputs.outside_assignments] == [
        (employee.id, sunday_close.id)
    ]
    assert inputs.shifts == []  # the Sunday close belongs to last week


# Generating and saving drafts

def test_generate_draft_saves_revision_one(db):
    demo = seed_demo_restaurant(db, employee_count=25)

    outcome = generate_draft(db, demo.restaurant_id, MONDAY, deterministic=True)

    schedule = outcome.schedule
    assert schedule is not None
    assert schedule.status == "draft"
    assert schedule.revision_number == 1
    assert schedule.solver_status == outcome.result.status
    assert schedule.fully_covered == outcome.result.fully_covered
    assert len(schedule.shortages) == len(outcome.result.shortages)
    assert schedule_assignments(db, schedule.id) == {
        shift_id: {role: sorted(ids) for role, ids in roles.items() if ids}
        for shift_id, roles in outcome.result.assignments.items()
        if any(roles.values())
    }


def test_each_new_draft_gets_the_next_revision_number(db):
    demo = seed_demo_restaurant(db, employee_count=25)

    first = generate_draft(db, demo.restaurant_id, MONDAY, deterministic=True).schedule
    second = generate_draft(db, demo.restaurant_id, MONDAY, deterministic=True).schedule

    assert (first.revision_number, second.revision_number) == (1, 2)


def test_impossible_week_saves_nothing(db):
    # The shift needs a cook, but the only employee is a server.
    restaurant = _add(db, models.Restaurant(name="Lanka Bistro", timezone="UTC"))
    cook = _add(db, models.Skill(restaurant_id=restaurant.id, name="cook"))
    server = _add(db, models.Skill(restaurant_id=restaurant.id, name="server"))
    asha = _add(db, models.Employee(
        restaurant_id=restaurant.id, display_name="Asha", max_minutes=2400,
    ))
    _add(db, models.EmployeeSkill(
        restaurant_id=restaurant.id, employee_id=asha.id, skill_id=server.id,
    ))
    _add(db, models.AvailabilityRule(
        employee_id=asha.id, weekday=0, start_time=time(9), end_time=time(17),
    ))
    shift = _add(db, models.Shift(
        restaurant_id=restaurant.id,
        starts_at=datetime(2026, 11, 23, 11, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 23, 15, tzinfo=timezone.utc),
    ))
    _add(db, models.ShiftRequirement(
        restaurant_id=restaurant.id, shift_id=shift.id, skill_id=cook.id, count=1, min_count=1,
    ))

    outcome = generate_draft(db, restaurant.id, MONDAY)

    assert outcome.result.status == "INFEASIBLE"
    assert outcome.schedule is None
    assert _count(db, models.Schedule) == 0


def test_restaurant_without_active_employees_is_reported(db):
    restaurant = _add(db, models.Restaurant(name="Lanka Bistro", timezone="UTC"))
    cook = _add(db, models.Skill(restaurant_id=restaurant.id, name="cook"))
    shift = _add(db, models.Shift(
        restaurant_id=restaurant.id,
        starts_at=datetime(2026, 11, 23, 11, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 23, 15, tzinfo=timezone.utc),
    ))
    _add(db, models.ShiftRequirement(
        restaurant_id=restaurant.id, shift_id=shift.id, skill_id=cook.id, count=1, min_count=1,
    ))

    with pytest.raises(ValueError, match="employee"):
        generate_draft(db, restaurant.id, MONDAY)

    assert _count(db, models.Schedule) == 0


def test_schedule_with_rule_violations_is_never_saved(db):
    demo = seed_demo_restaurant(db, employee_count=25)
    inputs = load_week(db, demo.restaurant_id, *week_bounds(MONDAY, UTC))
    broken = ScheduleResult(
        status="OPTIMAL",
        assignments={},
        validation_errors=("Shift 1: expected 2 employees, found 1.",),
    )

    with pytest.raises(EngineValidationError):
        save_revision(db, inputs, broken)
