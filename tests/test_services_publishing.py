"""Publishing schedules, recording call-outs and repairing published weeks."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from db import models
from optimizer.synthetic_data import pick_callout
from services.demo import seed_demo_restaurant
from services.scheduling import (
    ShortagesNotAcceptedError,
    StaleScheduleError,
    current_published,
    generate_draft,
    publish_schedule,
    record_absence,
    repair_published,
    schedule_assignments,
)

MONDAY = date(2026, 11, 23)
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def week(db):
    """A demo restaurant with a generated draft for its week."""
    demo = seed_demo_restaurant(db, employee_count=25)
    draft = generate_draft(db, demo.restaurant_id, MONDAY, deterministic=True).schedule
    assert draft is not None
    return demo, draft


def _publish(db, schedule):
    return publish_schedule(
        db, schedule.id, schedule.row_version, accept_shortages=True, now=NOW,
    )


def _repairable_callout(db, demo, published):
    """Record call-outs until one can be repaired; return (absence, outcome)."""
    assignments = schedule_assignments(db, published.id)
    for callout_seed in range(20):
        shift_id, employee_id = pick_callout(assignments, seed=callout_seed)
        savepoint = db.begin_nested()
        absence = record_absence(db, demo.restaurant_id, employee_id, shift_id)
        outcome = repair_published(db, demo.restaurant_id, MONDAY, deterministic=True)
        if outcome.schedule is not None:
            savepoint.commit()
            return absence, outcome
        savepoint.rollback()
    raise AssertionError("No repairable call-out found in 20 attempts.")


def _published_ids(db, restaurant_id):
    return db.scalars(
        select(models.Schedule.id).where(
            models.Schedule.restaurant_id == restaurant_id,
            models.Schedule.status == "published",
        )
    ).all()


# Publishing

def test_publishing_a_draft(db, week):
    demo, draft = week
    version = draft.row_version

    published = _publish(db, draft)

    assert published.status == "published"
    assert published.published_at == NOW
    assert published.row_version == version + 1


def test_shortages_need_confirmation(db, week):
    _, draft = week
    assert draft.shortages, "the demo week is a few positions short"

    with pytest.raises(ShortagesNotAcceptedError):
        publish_schedule(db, draft.id, draft.row_version)

    assert draft.status == "draft"


def test_outdated_version_is_refused(db, week):
    _, draft = week

    with pytest.raises(StaleScheduleError):
        publish_schedule(db, draft.id, draft.row_version - 1, accept_shortages=True)


def test_only_drafts_can_be_published(db, week):
    _, draft = week
    _publish(db, draft)

    with pytest.raises(ValueError, match="Only drafts"):
        publish_schedule(db, draft.id, draft.row_version, accept_shortages=True)


def test_unknown_schedule_is_reported(db):
    with pytest.raises(LookupError):
        publish_schedule(db, 999_999, 1)


def test_publishing_a_new_draft_archives_the_old_one(db, week):
    demo, first = week
    _publish(db, first)
    second = generate_draft(db, demo.restaurant_id, MONDAY, deterministic=True).schedule

    _publish(db, second)

    assert first.status == "archived"
    assert second.status == "published"
    assert _published_ids(db, demo.restaurant_id) == [second.id]


# Call-outs

def test_recording_a_callout(db, week):
    demo, draft = week
    _publish(db, draft)
    shift_id, employee_id = pick_callout(schedule_assignments(db, draft.id), seed=0)

    absence = record_absence(db, demo.restaurant_id, employee_id, shift_id, note="sick")
    db.refresh(absence)

    assert absence.rest_of_day is True
    assert absence.note == "sick"


def test_callout_needs_a_published_schedule(db, week):
    demo, draft = week
    shift_id, employee_id = pick_callout(schedule_assignments(db, draft.id), seed=0)

    with pytest.raises(ValueError, match="no published schedule"):
        record_absence(db, demo.restaurant_id, employee_id, shift_id)


def test_callout_for_someone_not_on_the_shift_is_refused(db, week):
    demo, draft = week
    _publish(db, draft)
    assignments = schedule_assignments(db, draft.id)
    shift_id = next(iter(assignments))
    on_shift = {e for ids in assignments[shift_id].values() for e in ids}
    off_shift = next(e for e in demo.employee_ids.values() if e not in on_shift)

    with pytest.raises(ValueError, match="not on shift"):
        record_absence(db, demo.restaurant_id, off_shift, shift_id)


def test_same_callout_twice_is_refused(db, week):
    demo, draft = week
    _publish(db, draft)
    shift_id, employee_id = pick_callout(schedule_assignments(db, draft.id), seed=0)
    record_absence(db, demo.restaurant_id, employee_id, shift_id)

    with pytest.raises(ValueError, match="already recorded"):
        record_absence(db, demo.restaurant_id, employee_id, shift_id)


def test_callout_for_another_restaurants_shift_is_refused(db, week):
    demo, draft = week
    _publish(db, draft)
    shift_id, employee_id = pick_callout(schedule_assignments(db, draft.id), seed=0)

    with pytest.raises(LookupError):
        record_absence(db, 999_999, employee_id, shift_id)


# Repairs

def test_repair_needs_a_published_schedule(db, week):
    demo, _ = week

    with pytest.raises(LookupError):
        repair_published(db, demo.restaurant_id, MONDAY)


def test_repair_is_saved_as_a_draft_based_on_the_published_revision(db, week):
    demo, draft = week
    published = _publish(db, draft)

    absence, outcome = _repairable_callout(db, demo, published)
    repair = outcome.schedule

    assert repair.status == "draft"
    assert repair.revision_number == 2
    assert repair.based_on_id == published.id
    assert repair.assignment_changes >= 1
    assert outcome.result.validation_errors == ()
    assert published.status == "published"  # until the repair is published

    repaired = schedule_assignments(db, repair.id)
    on_shift = {e for ids in repaired.get(absence.shift_id, {}).values() for e in ids}
    assert absence.employee_id not in on_shift


def test_called_out_employee_works_nothing_else_that_day(db, week):
    demo, draft = week
    published = _publish(db, draft)
    absence, outcome = _repairable_callout(db, demo, published)

    called_shift = db.get(models.Shift, absence.shift_id)
    for shift_id, roles in schedule_assignments(db, outcome.schedule.id).items():
        shift = db.get(models.Shift, shift_id)
        same_day = shift.starts_at.date() == called_shift.starts_at.date()
        if same_day and shift.starts_at >= called_shift.starts_at:
            assert absence.employee_id not in {e for ids in roles.values() for e in ids}


def test_publishing_the_repair_archives_the_original(db, week):
    demo, draft = week
    published = _publish(db, draft)
    _, outcome = _repairable_callout(db, demo, published)

    _publish(db, outcome.schedule)

    assert published.status == "archived"
    assert current_published(db, demo.restaurant_id, draft.period_start).id == outcome.schedule.id


def test_repair_of_an_outdated_revision_cannot_be_published(db, week):
    """Two repairs from the same revision: once one is published, the other is stale."""
    demo, draft = week
    published = _publish(db, draft)
    _, first = _repairable_callout(db, demo, published)
    second = repair_published(db, demo.restaurant_id, MONDAY, deterministic=True).schedule

    _publish(db, first.schedule)

    with pytest.raises(StaleScheduleError, match="no longer published"):
        _publish(db, second)


def test_full_flow_keeps_one_published_revision(db, week):
    demo, draft = week
    published = _publish(db, draft)
    _, outcome = _repairable_callout(db, demo, published)
    _publish(db, outcome.schedule)

    statuses = dict(db.execute(
        select(models.Schedule.revision_number, models.Schedule.status)
        .where(models.Schedule.restaurant_id == demo.restaurant_id)
    ).all())

    assert statuses == {1: "archived", 2: "published"}
    assert db.scalar(select(func.count()).select_from(models.Absence)) == 1
