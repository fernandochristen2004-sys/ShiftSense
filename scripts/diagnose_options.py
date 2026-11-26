"""Diagnose repair options for a recorded call-out. Read-only: saves nothing.

    python -m scripts.diagnose_options --restaurant 8 --name Hiro

Prints each option with its solver status per stage and how long it took,
so you can tell a proven-best repair (all OPTIMAL) from one cut short by the
time limit (FEASIBLE).
"""

import argparse
import time
from datetime import date

from db import models as db
from db.session import SessionLocal
from optimizer import engine
from services.callouts import exclusions_for_callouts
from services.loading import load_restaurant, load_week
from services.options import repair_options
from services.scheduling import current_published, full_original_schedule, week_callouts
from services.weeks import week_bounds
from zoneinfo import ZoneInfo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restaurant", type=int, required=True)
    parser.add_argument("--name", required=True, help="Who called out, e.g. Hiro")
    parser.add_argument("--week", default="2026-11-23", help="Monday of the week")
    args = parser.parse_args()
    week = date.fromisoformat(args.week)

    with SessionLocal() as session:
        names = {
            e.id: e.display_name
            for e in session.query(db.Employee).filter_by(restaurant_id=args.restaurant)
        }
        employee_id = next((i for i, n in names.items() if n == args.name), None)
        if employee_id is None:
            raise SystemExit(f"No employee called {args.name} in restaurant {args.restaurant}.")
        absences = (
            session.query(db.Absence)
            .filter_by(restaurant_id=args.restaurant, employee_id=employee_id)
            .all()
        )
        if not absences:
            raise SystemExit(f"{args.name} has no recorded call-out. Record one first.")
        absence = absences[-1]
        print(f"Call-out: {args.name} on shift {absence.shift_id}")
        print("Recorded call-outs this restaurant:",
              [(names[a.employee_id], a.shift_id) for a in
               session.query(db.Absence).filter_by(restaurant_id=args.restaurant)])

        # The plain repair, timed, with its stage statuses.
        restaurant = load_restaurant(session, args.restaurant)
        start, end = week_bounds(week, ZoneInfo(restaurant.timezone))
        inputs = load_week(session, args.restaurant, start, end)
        published = current_published(session, args.restaurant, start)
        original = full_original_schedule(session, published.id, inputs)
        excluded = exclusions_for_callouts(week_callouts(session, inputs), inputs.shifts, inputs.timezone)
        began = time.perf_counter()
        plain = engine.repair(
            employees=inputs.employees, shifts=inputs.shifts, policy=inputs.policy,
            original_schedule=original, outside_assignments=inputs.outside_assignments,
            excluded_assignments=excluded or None, scheduling_timezone=inputs.timezone,
            deterministic=True,
        )
        print(f"\nPlain repair: {time.perf_counter() - began:.2f}s, "
              f"changes={plain.assignment_changes}, stages={plain.stage_statuses}")

        # The smallest possible fix: everyone else stays exactly where they are.
        locked: dict[int, dict[str, list[int]]] = {}
        for shift_id, roles in original.items():
            for role, ids in roles.items():
                keep = [e for e in ids if e not in excluded.get(shift_id, [])]
                if keep:
                    locked.setdefault(shift_id, {})[role] = keep
        frozen = engine.repair(
            employees=inputs.employees, shifts=inputs.shifts, policy=inputs.policy,
            original_schedule=original, outside_assignments=inputs.outside_assignments,
            locked_assignments=locked, excluded_assignments=excluded or None,
            scheduling_timezone=inputs.timezone, deterministic=True,
        )
        frozen_missing = (
            None if frozen.assignments is None else sum(x.missing for x in frozen.shortages)
        )
        plain_missing = None if plain.assignments is None else sum(x.missing for x in plain.shortages)
        print(f"\nSmallest fix (everyone else kept): status={frozen.status}, "
              f"changes={frozen.assignment_changes}, missing={frozen_missing} "
              f"(plain repair missing={plain_missing})")
        if frozen.conflicts:
            print("  conflicts:", *frozen.conflicts, sep="\n    ")
        if frozen.validation_errors:
            print("  validation errors:", *frozen.validation_errors, sep="\n    ")
        if (frozen.assignments is not None and plain.assignments is not None
                and frozen_missing <= plain_missing
                and frozen.assignment_changes < plain.assignment_changes):
            print("  !! The smallest fix is better than the plain repair: please report this.")

        began = time.perf_counter()
        report = repair_options(session, args.restaurant, week, absence.shift_id, employee_id)
        print(f"\nOptions: {time.perf_counter() - began:.2f}s for all")
        for option in report.options:
            who = names[option.cover.employee_id] if option.cover else "(left empty)"
            print(f"  {who:12} changes={option.changes} missing={option.missing} "
                  f"stages={option.result.stage_statuses}")
        session.rollback()


if __name__ == "__main__":
    main()
