"""Clearing out old guest accounts and the demos they made.

Restaurants are never deleted by accident (their foreign keys RESTRICT), so
this removes a guest's restaurant data on purpose, children before parents.
The order comes from the models, so new tables are covered automatically.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from db import models as db

GUEST_DAYS = 7


def delete_restaurants(session: Session, restaurant_ids: list[int]) -> None:
    """Remove restaurants and everything in them. Only for data nobody needs."""
    if not restaurant_ids:
        return
    for table in reversed(db.Base.metadata.sorted_tables):  # children first
        if table.name != "restaurants" and "restaurant_id" in table.c:
            session.execute(delete(table).where(table.c.restaurant_id.in_(restaurant_ids)))
    session.execute(delete(db.Restaurant).where(db.Restaurant.id.in_(restaurant_ids)))
    session.flush()


def clean_up_guests(
    session: Session, older_than_days: int = GUEST_DAYS, limit: int = 20,
    now: datetime | None = None,
) -> int:
    """Delete up to `limit` guests older than `older_than_days`, with their demos.

    A restaurant is removed only if every member is one of those guests, so
    nothing a real account can see is ever touched. Returns guests removed.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=older_than_days)
    guest_ids = list(session.scalars(
        select(db.User.id)
        .where(db.User.is_guest.is_(True), db.User.created_at < cutoff)
        .order_by(db.User.id)
        .limit(limit)
    ))
    if not guest_ids:
        return 0

    theirs = select(db.Membership.restaurant_id).where(db.Membership.user_id.in_(guest_ids))
    shared = select(db.Membership.restaurant_id).where(
        db.Membership.restaurant_id.in_(theirs), db.Membership.user_id.not_in(guest_ids),
    )
    only_theirs = list(session.scalars(
        select(func.distinct(db.Membership.restaurant_id)).where(
            db.Membership.restaurant_id.in_(theirs), db.Membership.restaurant_id.not_in(shared),
        )
    ))

    delete_restaurants(session, only_theirs)
    session.execute(delete(db.User).where(db.User.id.in_(guest_ids)))  # sessions go with them
    session.flush()
    return len(guest_ids)
