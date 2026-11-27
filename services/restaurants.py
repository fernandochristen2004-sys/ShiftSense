"""Creating restaurants: an empty one to set up, or a demo with sample data.

Like the other services, these never commit.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import models as db
from services.demo import seed_demo_restaurant
from services.staff import clean_name

MAX_ROLES = 30


def create_restaurant(
    session: Session, name: str, timezone: str, roles: list[str]
) -> db.Restaurant:
    """An empty restaurant: no staff or shifts yet, just its roles.

    It gets the engine's default rules (no minimum rest, fair hours on);
    those can change later.
    """
    name = " ".join(name.split())
    if not name:
        raise ValueError("Give the restaurant a name.")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone {timezone!r}. Use a name like Asia/Colombo.") from exc

    role_names = sorted({clean_name(role, "Role name") for role in roles})
    if len(role_names) > MAX_ROLES:
        raise ValueError(f"At most {MAX_ROLES} roles.")

    restaurant = db.Restaurant(name=name, timezone=timezone)
    session.add(restaurant)
    session.flush()
    session.add(db.SchedulingPolicy(restaurant_id=restaurant.id))
    session.add_all(db.Skill(restaurant_id=restaurant.id, name=role) for role in role_names)
    session.flush()
    return restaurant


def create_demo(session: Session, reset: bool = False) -> db.Restaurant:
    """The demo bistro: 25 staff and a week of shifts, to try things out.

    There's one demo: the newest one. It's made the first time it's asked for;
    reset=True makes a fresh one. Older copies stay in the database (restaurants
    are never deleted, so no history is lost by accident) but aren't used.
    """
    if not reset:
        existing = session.scalars(
            select(db.Restaurant)
            .where(db.Restaurant.is_demo.is_(True))
            .order_by(db.Restaurant.id.desc())
            .limit(1)
        ).first()
        if existing is not None:
            return existing

    demo = seed_demo_restaurant(session, employee_count=25)
    return session.get(db.Restaurant, demo.restaurant_id)
