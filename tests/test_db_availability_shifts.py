"""Database rules for availability, policies, shifts and requirements."""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import (
    AvailabilityException,
    AvailabilityExceptionInterval,
    AvailabilityRule,
    Employee,
    Restaurant,
    SchedulingPolicy,
    Shift,
    ShiftRequirement,
    Skill,
)

MONDAY_11 = datetime(2026, 11, 23, 11, 0, tzinfo=timezone.utc)


def _add(db, record):
    db.add(record)
    db.flush()
    return record


def _restaurant(db, name="Lanka Bistro"):
    return _add(db, Restaurant(name=name, timezone="Asia/Colombo"))


def _employee(db, restaurant):
    return _add(db, Employee(restaurant_id=restaurant.id, display_name="Asha", max_minutes=2400))


def _skill(db, restaurant, name="server"):
    return _add(db, Skill(restaurant_id=restaurant.id, name=name))


def _shift(db, restaurant, start=MONDAY_11, hours=4, **fields):
    return _add(db, Shift(
        restaurant_id=restaurant.id,
        starts_at=start,
        ends_at=start + timedelta(hours=hours),
        **fields,
    ))


def _rejected(db, make):
    """Assert that the database rejects what `make` adds."""
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            make()
            db.flush()


# Weekly availability

def test_weekly_rule_is_saved(db):
    employee = _employee(db, _restaurant(db))
    rule = _add(db, AvailabilityRule(
        employee_id=employee.id, weekday=0, start_time=time(9), end_time=time(17),
    ))
    assert rule.id is not None


def test_overnight_weekly_rule_is_allowed(db):
    employee = _employee(db, _restaurant(db))
    rule = _add(db, AvailabilityRule(
        employee_id=employee.id, weekday=4, start_time=time(18), end_time=time(2),
    ))
    assert rule.end_time < rule.start_time


@pytest.mark.parametrize("weekday", [-1, 7])
def test_weekday_must_be_0_to_6(db, weekday):
    employee = _employee(db, _restaurant(db))
    _rejected(db, lambda: db.add(AvailabilityRule(
        employee_id=employee.id, weekday=weekday, start_time=time(9), end_time=time(17),
    )))


def test_empty_weekly_window_is_rejected(db):
    employee = _employee(db, _restaurant(db))
    _rejected(db, lambda: db.add(AvailabilityRule(
        employee_id=employee.id, weekday=0, start_time=time(9), end_time=time(9),
    )))


def test_weekly_times_need_minute_precision(db):
    employee = _employee(db, _restaurant(db))
    _rejected(db, lambda: db.add(AvailabilityRule(
        employee_id=employee.id, weekday=0, start_time=time(9, 0, 30), end_time=time(17),
    )))


# Date exceptions

def test_unavailable_exception_and_available_intervals_are_saved(db):
    employee = _employee(db, _restaurant(db))
    _add(db, AvailabilityException(employee_id=employee.id, local_date=date(2026, 11, 23), available=False))
    open_day = _add(db, AvailabilityException(
        employee_id=employee.id, local_date=date(2026, 11, 24), available=True, note="exam in the morning",
    ))
    _add(db, AvailabilityExceptionInterval(exception_id=open_day.id, start_time=time(14), end_time=time(22)))

    assert len(db.scalars(select(AvailabilityException)).all()) == 2


def test_one_exception_per_employee_per_date(db):
    employee = _employee(db, _restaurant(db))
    _add(db, AvailabilityException(employee_id=employee.id, local_date=date(2026, 11, 23), available=False))
    _rejected(db, lambda: db.add(AvailabilityException(
        employee_id=employee.id, local_date=date(2026, 11, 23), available=True,
    )))


def test_exception_interval_must_be_same_day_and_in_order(db):
    employee = _employee(db, _restaurant(db))
    exception = _add(db, AvailabilityException(
        employee_id=employee.id, local_date=date(2026, 11, 23), available=True,
    ))
    _rejected(db, lambda: db.add(AvailabilityExceptionInterval(
        exception_id=exception.id, start_time=time(22), end_time=time(2),
    )))


def test_deleting_an_employee_removes_their_availability(db):
    employee = _employee(db, _restaurant(db))
    _add(db, AvailabilityRule(employee_id=employee.id, weekday=0, start_time=time(9), end_time=time(17)))
    exception = _add(db, AvailabilityException(
        employee_id=employee.id, local_date=date(2026, 11, 24), available=True,
    ))
    _add(db, AvailabilityExceptionInterval(exception_id=exception.id, start_time=time(9), end_time=time(12)))

    db.delete(employee)
    db.flush()
    db.expunge_all()

    assert db.scalars(select(AvailabilityRule)).all() == []
    assert db.scalars(select(AvailabilityException)).all() == []
    assert db.scalars(select(AvailabilityExceptionInterval)).all() == []


# Scheduling policy

def test_policy_defaults_match_the_engine(db):
    restaurant = _restaurant(db)
    policy = _add(db, SchedulingPolicy(restaurant_id=restaurant.id))
    db.refresh(policy)

    assert policy.minimum_rest_minutes == 0
    assert policy.enforce_minimum_rest is False
    assert policy.allow_split_shifts is False
    assert policy.split_shift_min_break_minutes == 120
    assert policy.max_split_span_minutes == 780
    assert policy.fairness_enabled is True
    assert policy.allow_partial_coverage is False


def test_one_policy_per_restaurant(db):
    restaurant = _restaurant(db)
    _add(db, SchedulingPolicy(restaurant_id=restaurant.id))
    db.expunge_all()
    _rejected(db, lambda: db.add(SchedulingPolicy(restaurant_id=restaurant.id)))


def test_rest_must_be_whole_hours_for_now(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: db.add(SchedulingPolicy(restaurant_id=restaurant.id, minimum_rest_minutes=630)))


def test_split_span_must_exceed_split_break(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: db.add(SchedulingPolicy(
        restaurant_id=restaurant.id, split_shift_min_break_minutes=120, max_split_span_minutes=120,
    )))


def test_split_break_must_be_shorter_than_rest_when_both_are_on(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: db.add(SchedulingPolicy(
        restaurant_id=restaurant.id,
        enforce_minimum_rest=True,
        minimum_rest_minutes=120,
        allow_split_shifts=True,
        split_shift_min_break_minutes=120,
    )))


def test_split_break_is_free_when_rest_is_off(db):
    restaurant = _restaurant(db)
    policy = _add(db, SchedulingPolicy(
        restaurant_id=restaurant.id, allow_split_shifts=True, split_shift_min_break_minutes=120,
    ))
    assert policy.restaurant_id == restaurant.id


# Shifts

def test_times_come_back_in_utc(db):
    restaurant = _restaurant(db)
    shift = _shift(db, restaurant)
    db.refresh(shift)

    assert shift.starts_at == MONDAY_11
    assert shift.starts_at.utcoffset() == timedelta(0)


def test_overnight_shift_is_saved_as_active(db):
    restaurant = _restaurant(db)
    shift = _shift(db, restaurant, start=MONDAY_11 + timedelta(hours=12), hours=3, label="Late close")
    db.refresh(shift)
    assert shift.status == "active"
    assert shift.ends_at.date() > shift.starts_at.date()


def test_shift_must_end_after_it_starts(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: db.add(Shift(restaurant_id=restaurant.id, starts_at=MONDAY_11, ends_at=MONDAY_11)))


def test_shift_status_is_active_or_cancelled(db):
    restaurant = _restaurant(db)
    assert _shift(db, restaurant, status="cancelled").status == "cancelled"
    _rejected(db, lambda: _shift(db, restaurant, status="deleted"))


def test_shift_times_need_minute_precision(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: _shift(db, restaurant, start=MONDAY_11 + timedelta(seconds=30)))


# Shift requirements

def test_requirement_with_a_shortfall_allowance_is_saved(db):
    restaurant = _restaurant(db)
    shift, skill = _shift(db, restaurant), _skill(db, restaurant)
    requirement = _add(db, ShiftRequirement(
        restaurant_id=restaurant.id, shift_id=shift.id, skill_id=skill.id, count=3, min_count=2,
    ))
    assert (requirement.count, requirement.min_count) == (3, 2)


@pytest.mark.parametrize("count, min_count", [(2, 3), (2, -1), (-1, 0)])
def test_requirement_counts_must_make_sense(db, count, min_count):
    restaurant = _restaurant(db)
    shift, skill = _shift(db, restaurant), _skill(db, restaurant)
    _rejected(db, lambda: db.add(ShiftRequirement(
        restaurant_id=restaurant.id, shift_id=shift.id, skill_id=skill.id, count=count, min_count=min_count,
    )))


def test_a_role_appears_once_per_shift(db):
    restaurant = _restaurant(db)
    shift, skill = _shift(db, restaurant), _skill(db, restaurant)
    _add(db, ShiftRequirement(restaurant_id=restaurant.id, shift_id=shift.id, skill_id=skill.id, count=2, min_count=2))
    _rejected(db, lambda: db.add(ShiftRequirement(
        restaurant_id=restaurant.id, shift_id=shift.id, skill_id=skill.id, count=1, min_count=1,
    )))


def test_requirement_cannot_use_another_restaurants_skill(db):
    first, second = _restaurant(db), _restaurant(db, "Harbour Cafe")
    shift = _shift(db, first)
    other_skill = _skill(db, second, "cook")
    _rejected(db, lambda: db.add(ShiftRequirement(
        restaurant_id=first.id, shift_id=shift.id, skill_id=other_skill.id, count=1, min_count=1,
    )))


def test_deleting_a_shift_removes_its_requirements(db):
    restaurant = _restaurant(db)
    shift, skill = _shift(db, restaurant), _skill(db, restaurant)
    _add(db, ShiftRequirement(restaurant_id=restaurant.id, shift_id=shift.id, skill_id=skill.id, count=1, min_count=1))

    db.delete(shift)
    db.flush()
    db.expunge_all()

    assert db.scalars(select(ShiftRequirement)).all() == []


def test_skill_used_by_a_shift_cannot_be_deleted(db):
    restaurant = _restaurant(db)
    shift, skill = _shift(db, restaurant), _skill(db, restaurant)
    _add(db, ShiftRequirement(restaurant_id=restaurant.id, shift_id=shift.id, skill_id=skill.id, count=1, min_count=1))

    def delete_skill():
        db.delete(skill)

    _rejected(db, delete_skill)
