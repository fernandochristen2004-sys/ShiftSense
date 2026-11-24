"""Store a demo restaurant in your database and generate its first draft.

Run from the project root, with the database running:
    python -m scripts.seed_demo
    python -m scripts.seed_demo --staff 40 --seed 3

Each run adds a new demo restaurant; nothing existing is changed.
"""

import argparse

from sqlalchemy import func, select

from db import models
from db.session import SessionLocal
from services.demo import seed_demo_restaurant
from services.scheduling import generate_draft


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed a demo restaurant")
    parser.add_argument("--staff", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        demo = seed_demo_restaurant(session, employee_count=args.staff, seed=args.seed)
        outcome = generate_draft(session, demo.restaurant_id, demo.week_start, deterministic=True)
        session.commit()

        print(f"Restaurant {demo.restaurant_id}: {args.staff} staff, "
              f"{len(demo.shift_ids)} shifts, week of {demo.week_start:%d %b %Y}")
        print(f"Engine result: {outcome.result.status}")

        schedule = outcome.schedule
        if schedule is None:
            print("No schedule was possible, so nothing was saved.")
            return

        assignments = session.scalar(
            select(func.count()).where(models.Assignment.schedule_id == schedule.id)
        )
        missing = sum(s["missing"] for s in schedule.shortages)
        print(f"Saved draft revision {schedule.revision_number} (schedule {schedule.id}): "
              f"{assignments} assignments, {missing} position(s) short")


if __name__ == "__main__":
    main()
