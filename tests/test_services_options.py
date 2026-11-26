"""Ranked replacements: several complete ways to cover a call-out."""

from datetime import date, datetime, timezone

import pytest

from services.demo import seed_demo_restaurant
from services.options import repair_options
from services.risk import callout_risk
from services.scheduling import (
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
    """A published demo week and its call-out risk report."""
    demo = seed_demo_restaurant(db, employee_count=25)
    draft = generate_draft(db, demo.restaurant_id, MONDAY, deterministic=True).schedule
    publish_schedule(db, draft.id, draft.row_version, accept_shortages=True, now=NOW)
    return demo, callout_risk(db, demo.restaurant_id, MONDAY)


def _call_out(db, demo, risk):
    record_absence(db, demo.restaurant_id, risk.employee_id, risk.shift_id)
    return repair_options(db, demo.restaurant_id, MONDAY, risk.shift_id, risk.employee_id)


def test_options_cover_the_slot_and_are_ranked(db, week):
    demo, report = week
    covered = [r for r in report.risks if r.level == "covered"]
    # A call-out with more than one possible replacement.
    for risk in covered:
        savepoint = db.begin_nested()
        options = _call_out(db, demo, risk)
        if len(options.options) > 1:
            break
        savepoint.rollback()
    else:
        pytest.skip("no call-out with several options in this demo week")

    assert options.role == risk.role
    assert options.why is None
    keys = [option.rank_key() for option in options.options]
    assert keys == sorted(keys)
    assert len(options.options) <= 3

    covers = [option.cover.employee_id for option in options.options if option.cover]
    assert len(covers) == len(set(covers))  # one option per person

    for option in options.options:
        slot = option.result.assignments[risk.shift_id][risk.role]
        assert risk.employee_id not in slot
        if option.cover:
            assert option.cover.employee_id in slot
            assert option.cover_minutes > 0

    # The best option is as good as the plain repair the report predicted.
    best = options.options[0]
    assert best.missing == report.baseline_missing
    assert best.changes == risk.changes


def test_choosing_an_option_saves_exactly_that_option(db, week):
    demo, report = week
    for risk in (r for r in report.risks if r.level == "covered"):
        savepoint = db.begin_nested()
        options = _call_out(db, demo, risk)
        if len(options.options) > 1 and options.options[-1].cover:
            break
        savepoint.rollback()
    else:
        pytest.skip("no call-out with several options in this demo week")

    chosen = options.options[-1]  # not the default: prove the choice is kept
    outcome = repair_published(
        db, demo.restaurant_id, MONDAY, deterministic=True,
        cover=(chosen.cover.shift_id, chosen.cover.role, chosen.cover.employee_id),
    )

    saved = schedule_assignments(db, outcome.schedule.id)
    expected = {
        shift_id: {role: sorted(ids) for role, ids in roles.items() if ids}
        for shift_id, roles in chosen.result.assignments.items()
    }
    assert {
        shift_id: {role: sorted(ids) for role, ids in roles.items()}
        for shift_id, roles in saved.items()
    } == {shift_id: roles for shift_id, roles in expected.items() if roles}
    assert outcome.schedule.assignment_changes == chosen.changes


def test_when_nobody_can_cover_it_says_why(db, week):
    demo, report = week
    short = next(r for r in report.risks if r.level == "short")

    options = _call_out(db, demo, short)

    assert all(option.cover is None for option in options.options)
    assert options.why is not None
    assert " is off " in options.why.summary


def test_the_callout_must_be_recorded_first(db, week):
    demo, report = week
    risk = report.risks[0]

    with pytest.raises(ValueError, match="Record the call-out first"):
        repair_options(db, demo.restaurant_id, MONDAY, risk.shift_id, risk.employee_id)


def test_the_person_must_be_on_the_shift(db, week):
    demo, report = week
    risk = report.risks[0]
    on_shift = {r.employee_id for r in report.risks if r.shift_id == risk.shift_id}
    other = next(r for r in report.risks if r.employee_id not in on_shift)

    with pytest.raises(ValueError, match="is not on shift"):
        repair_options(db, demo.restaurant_id, MONDAY, risk.shift_id, other.employee_id)


def test_someone_already_in_the_slot_is_not_offered(db, week):
    """A coworker already on the shift in the same role isn't a replacement,
    and every option names the person who really fills the slot."""
    demo, report = week
    published = schedule_assignments(db, report.schedule_id)
    checked = 0
    for risk in (r for r in report.risks if r.level == "covered"):
        coworkers = set(published[risk.shift_id][risk.role]) - {risk.employee_id}
        if not coworkers:
            continue
        savepoint = db.begin_nested()
        options = _call_out(db, demo, risk)
        for option in options.options:
            if option.cover:
                assert option.cover.employee_id not in coworkers
                slot = option.result.assignments[risk.shift_id][risk.role]
                assert option.cover.employee_id in slot
        savepoint.rollback()
        checked += 1
    assert checked, "expected slots with two people in the demo week"
