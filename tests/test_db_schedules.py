"""Database rules for schedules, assignments, locks and absences."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from db.models import (
    Absence,
    Assignment,
    Employee,
    Lock,
    Restaurant,
    Schedule,
    Shift,
    Skill,
)

WEEK = datetime(2026, 11, 23, tzinfo=timezone.utc)  # a Monday
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def _add(db, record):
    db.add(record)
    db.flush()
    return record


def _rejected(db, make, error=IntegrityError):
    """Assert that the database rejects what `make` adds or changes."""
    with pytest.raises(error):
        with db.begin_nested():
            make()
            db.flush()


@pytest.fixture
def place(db):
    """A restaurant with one employee, one skill and one shift."""
    restaurant = _add(db, Restaurant(name="Lanka Bistro", timezone="Asia/Colombo"))
    employee = _add(db, Employee(restaurant_id=restaurant.id, display_name="Asha", max_minutes=2400))
    skill = _add(db, Skill(restaurant_id=restaurant.id, name="server"))
    shift = _add(db, Shift(
        restaurant_id=restaurant.id,
        starts_at=WEEK + timedelta(hours=11),
        ends_at=WEEK + timedelta(hours=15),
    ))
    return restaurant, employee, skill, shift


def _schedule(db, restaurant, revision=1, **fields):
    return _add(db, Schedule(
        restaurant_id=restaurant.id,
        period_start=WEEK,
        period_end=WEEK + timedelta(days=7),
        revision_number=revision,
        **fields,
    ))


def _other_restaurant(db):
    restaurant = _add(db, Restaurant(name="Harbour Cafe", timezone="Asia/Colombo"))
    employee = _add(db, Employee(restaurant_id=restaurant.id, display_name="Ben", max_minutes=2400))
    skill = _add(db, Skill(restaurant_id=restaurant.id, name="server"))
    return restaurant, employee, skill


# Schedules

def test_new_schedule_starts_as_a_draft(db, place):
    schedule = _schedule(db, place[0])
    db.refresh(schedule)

    assert schedule.status == "draft"
    assert schedule.row_version == 1
    assert schedule.shortages == []
    assert schedule.objective_values == {}


def test_results_are_stored_as_json(db, place):
    schedule = _schedule(
        db,
        place[0],
        solver_status="OPTIMAL",
        fully_covered=False,
        shortages=[{"shift_id": 1, "role": "server", "missing": 1}],
        objective_values={"coverage_shortage": 1},
    )
    db.expire(schedule)

    assert schedule.shortages == [{"shift_id": 1, "role": "server", "missing": 1}]
    assert schedule.objective_values == {"coverage_shortage": 1}


def test_shortages_must_be_a_list(db, place):
    _rejected(db, lambda: _schedule(db, place[0], shortages={"missing": 1}))


def test_period_must_end_after_it_starts(db, place):
    _rejected(db, lambda: db.add(Schedule(
        restaurant_id=place[0].id, period_start=WEEK, period_end=WEEK, revision_number=1,
    )))


def test_revision_numbers_are_unique_per_period(db, place):
    _schedule(db, place[0], revision=1)
    _rejected(db, lambda: _schedule(db, place[0], revision=1))


def test_revision_numbers_start_at_one(db, place):
    _rejected(db, lambda: _schedule(db, place[0], revision=0))


def test_unknown_status_is_rejected(db, place):
    _rejected(db, lambda: _schedule(db, place[0], status="final"))


def test_published_schedule_needs_a_publish_time(db, place):
    _rejected(db, lambda: _schedule(db, place[0], status="published"))


def test_only_one_published_schedule_per_period(db, place):
    _schedule(db, place[0], revision=1, status="published", published_at=NOW)
    _rejected(db, lambda: _schedule(db, place[0], revision=2, status="published", published_at=NOW))


def test_drafts_and_archived_revisions_can_sit_beside_the_published_one(db, place):
    _schedule(db, place[0], revision=1, status="archived", published_at=NOW)
    _schedule(db, place[0], revision=2, status="published", published_at=NOW)
    draft = _schedule(db, place[0], revision=3)

    assert draft.status == "draft"


def test_publishing_a_new_revision_works_after_archiving_the_old_one(db, place):
    old = _schedule(db, place[0], revision=1, status="published", published_at=NOW)
    new = _schedule(db, place[0], revision=2, based_on_id=old.id)

    old.status = "archived"
    new.status, new.published_at = "published", NOW
    db.flush()

    published = db.scalars(select(Schedule).where(Schedule.status == "published")).one()
    assert published.revision_number == 2
    assert published.based_on_id == old.id


def test_revision_cannot_be_based_on_another_restaurants_schedule(db, place):
    other, _, _ = _other_restaurant(db)
    foreign = _schedule(db, other)
    _rejected(db, lambda: _schedule(db, place[0], based_on_id=foreign.id))


def test_stale_update_is_rejected(db, place):
    """Two managers editing the same schedule: the second, outdated save fails."""
    schedule = _schedule(db, place[0])
    assert schedule.row_version == 1

    # Another manager saves first, which bumps the version.
    db.execute(
        text("update schedules set row_version = row_version + 1 where id = :id"),
        {"id": schedule.id},
    )

    def outdated_save():
        schedule.solver_status = "OPTIMAL"

    _rejected(db, outdated_save, error=StaleDataError)


def test_each_save_increments_the_version(db, place):
    schedule = _schedule(db, place[0])
    schedule.solver_status = "OPTIMAL"
    db.flush()

    assert schedule.row_version == 2


# Assignments

def _assignment(db, schedule, employee, shift, skill, restaurant_id=None):
    return Assignment(
        restaurant_id=restaurant_id or schedule.restaurant_id,
        schedule_id=schedule.id,
        shift_id=shift.id,
        employee_id=employee.id,
        skill_id=skill.id,
    )


def test_assignment_is_saved(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    _add(db, _assignment(db, schedule, employee, shift, skill))

    assert len(db.scalars(select(Assignment)).all()) == 1


def test_one_role_per_person_per_shift(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    host = _add(db, Skill(restaurant_id=restaurant.id, name="host"))
    _add(db, _assignment(db, schedule, employee, shift, skill))

    _rejected(db, lambda: db.add(_assignment(db, schedule, employee, shift, host)))


def test_same_person_and_shift_in_another_revision_is_fine(db, place):
    restaurant, employee, skill, shift = place
    first = _schedule(db, restaurant, revision=1)
    second = _schedule(db, restaurant, revision=2)
    _add(db, _assignment(db, first, employee, shift, skill))
    _add(db, _assignment(db, second, employee, shift, skill))

    assert len(db.scalars(select(Assignment)).all()) == 2


def test_assignment_cannot_use_another_restaurants_employee(db, place):
    restaurant, _, skill, shift = place
    _, foreign_employee, _ = _other_restaurant(db)
    schedule = _schedule(db, restaurant)

    _rejected(db, lambda: db.add(_assignment(db, schedule, foreign_employee, shift, skill)))


def test_deleting_a_schedule_removes_its_assignments(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    _add(db, _assignment(db, schedule, employee, shift, skill))

    db.delete(schedule)
    db.flush()
    db.expunge_all()

    assert db.scalars(select(Assignment)).all() == []


def test_employee_with_assignments_cannot_be_deleted(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    _add(db, _assignment(db, schedule, employee, shift, skill))

    def delete_employee():
        db.delete(employee)

    _rejected(db, delete_employee)


def test_shift_with_assignments_cannot_be_deleted(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    _add(db, _assignment(db, schedule, employee, shift, skill))

    def delete_shift():
        db.delete(shift)

    _rejected(db, delete_shift)


# Locks

def _lock(schedule, employee, shift, kind, skill=None):
    return Lock(
        restaurant_id=schedule.restaurant_id,
        schedule_id=schedule.id,
        shift_id=shift.id,
        employee_id=employee.id,
        skill_id=skill.id if skill else None,
        kind=kind,
    )


def test_must_work_and_must_not_work_locks_are_saved(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    other = _add(db, Employee(restaurant_id=restaurant.id, display_name="Ben", max_minutes=2400))

    _add(db, _lock(schedule, employee, shift, "must_work", skill))
    _add(db, _lock(schedule, other, shift, "must_not_work"))

    assert len(db.scalars(select(Lock)).all()) == 2


def test_must_work_lock_needs_a_role(db, place):
    restaurant, employee, _, shift = place
    schedule = _schedule(db, restaurant)
    _rejected(db, lambda: db.add(_lock(schedule, employee, shift, "must_work")))


def test_must_not_work_lock_has_no_role(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    _rejected(db, lambda: db.add(_lock(schedule, employee, shift, "must_not_work", skill)))


def test_lock_cannot_say_both_work_and_not_work(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    _add(db, _lock(schedule, employee, shift, "must_work", skill))
    _rejected(db, lambda: db.add(_lock(schedule, employee, shift, "must_not_work")))


def test_unknown_lock_kind_is_rejected(db, place):
    restaurant, employee, skill, shift = place
    schedule = _schedule(db, restaurant)
    _rejected(db, lambda: db.add(_lock(schedule, employee, shift, "maybe", skill)))


def test_lock_cannot_use_another_restaurants_role(db, place):
    restaurant, employee, _, shift = place
    _, _, foreign_skill = _other_restaurant(db)
    schedule = _schedule(db, restaurant)
    _rejected(db, lambda: db.add(_lock(schedule, employee, shift, "must_work", foreign_skill)))


# Absences

def test_absence_is_saved_with_defaults(db, place):
    restaurant, employee, _, shift = place
    absence = _add(db, Absence(restaurant_id=restaurant.id, employee_id=employee.id, shift_id=shift.id))
    db.refresh(absence)

    assert absence.rest_of_day is True
    assert absence.reported_at is not None


def test_one_absence_per_employee_per_shift(db, place):
    restaurant, employee, _, shift = place
    _add(db, Absence(restaurant_id=restaurant.id, employee_id=employee.id, shift_id=shift.id))
    _rejected(db, lambda: db.add(Absence(
        restaurant_id=restaurant.id, employee_id=employee.id, shift_id=shift.id,
    )))


def test_absence_cannot_mix_restaurants(db, place):
    restaurant, _, _, shift = place
    _, foreign_employee, _ = _other_restaurant(db)
    _rejected(db, lambda: db.add(Absence(
        restaurant_id=restaurant.id, employee_id=foreign_employee.id, shift_id=shift.id,
    )))
