"""Call-out risk: simulate every call-out in a published week."""

from datetime import date, datetime, timezone

import pytest

from services.demo import seed_demo_restaurant
from services.risk import callout_risk
from services.scheduling import (
    cancel_absence,
    generate_draft,
    publish_schedule,
    record_absence,
    repair_published,
    schedule_assignments,
)

MONDAY = date(2026, 11, 23)
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def published(db):
    """A demo restaurant with its week published."""
    demo = seed_demo_restaurant(db, employee_count=25)
    draft = generate_draft(db, demo.restaurant_id, MONDAY, deterministic=True).schedule
    publish_schedule(db, draft.id, draft.row_version, accept_shortages=True, now=NOW)
    return demo, draft


def _assignment_count(db, schedule_id):
    return sum(
        len(ids)
        for roles in schedule_assignments(db, schedule_id).values()
        for ids in roles.values()
    )


def test_every_assignment_is_checked(db, published):
    demo, schedule = published

    report = callout_risk(db, demo.restaurant_id, MONDAY)

    assert report.schedule_id == schedule.id
    assert len(report.risks) == _assignment_count(db, schedule.id)
    assert report.baseline_missing == sum(s["missing"] for s in schedule.shortages)
    assert {risk.level for risk in report.risks} <= {"covered", "short", "no_fix"}

    # The demo week is tight: most call-outs can be absorbed, but not all.
    levels = [risk.level for risk in report.risks]
    assert levels.count("covered") > len(levels) // 2
    assert report.at_risk

    for risk in report.risks:
        if risk.level == "no_fix":
            assert risk.extra_missing is None and risk.changes is None
            assert " is off " in risk.why.summary
            assert risk.why.explanation.gaps
        else:
            assert risk.why is None
            assert risk.changes >= 1  # at least the called-out person comes off
            assert (risk.extra_missing > 0) == (risk.level == "short")


def test_predictions_match_real_repairs(db, published):
    """Recording the call-out and repairing gives the outcome the report predicted."""
    demo, _ = published
    report = callout_risk(db, demo.restaurant_id, MONDAY)

    for level in ("covered", "no_fix"):
        risk = next(r for r in report.risks if r.level == level)
        savepoint = db.begin_nested()
        record_absence(db, demo.restaurant_id, risk.employee_id, risk.shift_id)
        outcome = repair_published(db, demo.restaurant_id, MONDAY, deterministic=True)

        if level == "no_fix":
            assert outcome.schedule is None
        else:
            assert outcome.schedule is not None
            missing = sum(s["missing"] for s in outcome.schedule.shortages)
            assert missing == report.baseline_missing
            assert outcome.schedule.assignment_changes == risk.changes
        savepoint.rollback()


def test_recorded_callouts_are_skipped(db, published):
    demo, schedule = published
    report = callout_risk(db, demo.restaurant_id, MONDAY)
    covered = next(r for r in report.risks if r.level == "covered")

    record_absence(
        db, demo.restaurant_id, covered.employee_id, covered.shift_id, rest_of_day=False
    )
    after = callout_risk(db, demo.restaurant_id, MONDAY)

    checked = {(r.shift_id, r.employee_id) for r in after.risks}
    assert (covered.shift_id, covered.employee_id) not in checked
    assert len(after.risks) == len(report.risks) - 1


def test_an_unfixable_recorded_callout_is_reported_once(db, published):
    """If the week already can't be repaired, say so instead of marking everyone."""
    demo, _ = published
    report = callout_risk(db, demo.restaurant_id, MONDAY)
    assert report.week_fixable
    no_fix = next(r for r in report.risks if r.level == "no_fix")

    record_absence(db, demo.restaurant_id, no_fix.employee_id, no_fix.shift_id)
    after = callout_risk(db, demo.restaurant_id, MONDAY)

    assert not after.week_fixable
    assert after.risks == []
    assert after.blocker == no_fix.why


def test_cancelling_the_callout_makes_the_week_fixable_again(db, published):
    demo, _ = published
    report = callout_risk(db, demo.restaurant_id, MONDAY)
    no_fix = next(r for r in report.risks if r.level == "no_fix")
    absence = record_absence(db, demo.restaurant_id, no_fix.employee_id, no_fix.shift_id)
    assert not callout_risk(db, demo.restaurant_id, MONDAY).week_fixable

    cancel_absence(db, demo.restaurant_id, absence.id)

    assert callout_risk(db, demo.restaurant_id, MONDAY).week_fixable


def test_needs_a_published_schedule(db):
    demo = seed_demo_restaurant(db, employee_count=25)
    generate_draft(db, demo.restaurant_id, MONDAY, deterministic=True)

    with pytest.raises(LookupError, match="no published schedule"):
        callout_risk(db, demo.restaurant_id, MONDAY)
