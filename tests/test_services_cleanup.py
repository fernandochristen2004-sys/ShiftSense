"""Tests for clearing out old guests and their demos."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, update

from db import models
from services.accounts import add_member, create_guest, sign_up, start_session
from services.cleanup import clean_up_guests
from services.restaurants import create_demo
from services.scheduling import (
    generate_draft,
    publish_schedule,
    record_absence,
    repair_published,
)
from services.week_plans import save_template

MONDAY = date(2026, 11, 23)
LONG_AGO = datetime.now(UTC) - timedelta(days=30)


def _guest_with_a_busy_demo(db) -> tuple[int, int]:
    """A guest whose demo has a published week, a call-out, a repair and a template."""
    guest = create_guest(db)
    start_session(db, guest)
    demo = create_demo(db, owner_id=guest.id).id

    draft = generate_draft(db, demo, MONDAY, deterministic=True).schedule
    published = publish_schedule(db, draft.id, draft.row_version, accept_shortages=True)
    first = db.scalars(
        select(models.Assignment).where(models.Assignment.schedule_id == published.id)
    ).first()
    record_absence(db, demo, first.employee_id, first.shift_id)
    repair_published(db, demo, MONDAY, deterministic=True)
    save_template(db, demo, "Normal week", MONDAY)
    return guest.id, demo


def _age(db, user_id: int) -> None:
    db.execute(update(models.User).where(models.User.id == user_id).values(created_at=LONG_AGO))


def _rows_left(db, restaurant_id: int) -> dict[str, int]:
    counts = {}
    for table in models.Base.metadata.sorted_tables:
        column = table.c.get("restaurant_id") if table.name != "restaurants" else table.c.id
        if column is not None:
            counts[table.name] = db.scalar(
                select(func.count()).select_from(table).where(column == restaurant_id)
            )
    return {name: n for name, n in counts.items() if n}


def test_an_old_guest_and_everything_in_their_demo_are_removed(db):
    guest_id, demo = _guest_with_a_busy_demo(db)
    assert len(_rows_left(db, demo)) > 5  # really is a busy demo
    _age(db, guest_id)

    assert clean_up_guests(db) == 1
    assert _rows_left(db, demo) == {}
    assert db.get(models.User, guest_id) is None
    assert db.scalar(
        select(func.count()).select_from(models.UserSession)
        .where(models.UserSession.user_id == guest_id)
    ) == 0


def test_recent_guests_are_kept(db):
    guest_id, demo = _guest_with_a_busy_demo(db)
    assert clean_up_guests(db) == 0
    assert db.get(models.User, guest_id) is not None
    assert _rows_left(db, demo)


def test_a_guest_who_signed_up_is_never_removed(db):
    guest_id, demo = _guest_with_a_busy_demo(db)
    sign_up(db, "ana@example.com", "correct horse battery", guest=db.get(models.User, guest_id))
    _age(db, guest_id)

    assert clean_up_guests(db) == 0
    assert _rows_left(db, demo)


def test_a_restaurant_a_real_account_can_see_is_kept(db):
    guest_id, demo = _guest_with_a_busy_demo(db)
    ana = sign_up(db, "ana@example.com", "correct horse battery")
    add_member(db, ana.id, demo, role="manager")
    _age(db, guest_id)

    assert clean_up_guests(db) == 1
    assert db.get(models.User, guest_id) is None
    assert _rows_left(db, demo)  # Ana still has it


def test_other_restaurants_are_untouched(db):
    guest_id, _ = _guest_with_a_busy_demo(db)
    _, other = _guest_with_a_busy_demo(db)  # a recent guest's demo
    before = _rows_left(db, other)
    _age(db, guest_id)

    clean_up_guests(db)
    assert _rows_left(db, other) == before
