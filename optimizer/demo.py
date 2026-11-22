"""ShiftSense demo: generate a week, simulate a call-out, repair it.

The demo runs the solver in deterministic mode, so the same command always
shows the same schedule and repair.

Run from the project root:
    python -m optimizer.demo
    python -m optimizer.demo --staff 40 --seed 3
"""

import argparse
import time

from optimizer import engine
from optimizer.synthetic_data import (
    apply_callout,
    generate_restaurant_scenario,
    pick_callout,
)

# Friendly names for the demo only. The generator names staff "Employee N".
DEMO_NAMES = (
    "Asha", "Ben", "Chamari", "Dilan", "Elena", "Farhan", "Gaya", "Hiro",
    "Isuru", "Jade", "Kasun", "Lina", "Malik", "Nimmi", "Omar", "Priya",
    "Quinn", "Ravi", "Sara", "Tharindu", "Uma", "Viktor", "Wen", "Yasmin",
    "Zane", "Amaya", "Bilal", "Carmen", "Dev", "Esha", "Felix", "Gihan",
    "Hana", "Ishan", "Julia", "Kavi", "Leo", "Maya", "Nuwan", "Olivia",
)


def _name(employee_id: int) -> str:
    if employee_id <= len(DEMO_NAMES):
        return DEMO_NAMES[employee_id - 1]
    return f"Employee {employee_id}"


def _shift_label(shift) -> str:
    start, end = shift.starts_at, shift.ends_at
    names = {11: "lunch", 17: "dinner", 23: "late close"}
    part = names.get(start.hour, "shift")
    return f"{start:%a %d %b} {part} ({start:%H:%M}–{end:%H:%M})"


def _missing(result) -> int:
    return sum(shortage.missing for shortage in result.shortages)


def print_schedule(shifts, assignments) -> None:
    for shift in shifts:
        print(f"\n{_shift_label(shift)}")
        for requirement in shift.requirements:
            ids = assignments.get(shift.id, {}).get(requirement.skill, [])
            names = ", ".join(_name(i) for i in sorted(ids)) or "nobody"
            short = requirement.count - len(ids)
            note = f"   ({short} short)" if short > 0 else ""
            print(f"  {requirement.skill:<10} {names}{note}")


def print_shortages(result, shifts_by_id) -> None:
    if not result.shortages:
        print("Every position is filled.")
        return

    print(f"{_missing(result)} position(s) short, but every hard minimum is met:")
    for shortage in result.shortages:
        shift = shifts_by_id[shortage.shift_id]
        print(f"  - {_shift_label(shift)}: {shortage.missing} {shortage.role} short")


def _role_of(assignments, shift_id, employee_id):
    for role, ids in assignments.get(shift_id, {}).items():
        if employee_id in ids:
            return role
    return None


def print_changes(original, repaired, shifts) -> None:
    """Describe what the repair changed, in plain English."""
    lines = []

    for shift in shifts:
        removed, switched, added = [], [], []

        before = {
            e: r for r, ids in original.get(shift.id, {}).items() for e in ids
        }
        after = {
            e: r for r, ids in repaired.get(shift.id, {}).items() for e in ids
        }

        for employee_id in sorted(before.keys() | after.keys()):
            old_role = before.get(employee_id)
            new_role = after.get(employee_id)
            if old_role == new_role:
                continue

            who = _name(employee_id)
            where = _shift_label(shift)
            if new_role is None:
                removed.append(f"  - {who} is taken off {where} ({old_role})")
            elif old_role is None:
                added.append(f"  + {who} is added to {where} as {new_role}")
            else:
                switched.append(f"  ~ {who} switches from {old_role} to {new_role} on {where}")

        # Read naturally: who leaves, who changes role, then who fills in.
        lines += removed + switched + added

    if lines:
        print("\n".join(lines))
    print("  Nobody else's schedule changes.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ShiftSense demo")
    parser.add_argument("--staff", type=int, default=25, help="restaurant size (18+ recommended)")
    parser.add_argument("--seed", type=int, default=42, help="which synthetic restaurant")
    args = parser.parse_args(argv)

    scenario = generate_restaurant_scenario(args.staff, seed=args.seed)
    shifts = sorted(scenario.shifts, key=lambda s: s.starts_at)
    shifts_by_id = {s.id: s for s in shifts}

    roles = sorted({skill for e in scenario.employees for skill in e.skills})
    print("ShiftSense demo")
    print("=" * 60)
    print(f"Restaurant: {args.staff} staff ({', '.join(roles)}), {len(shifts)} shifts, "
          f"synthetic seed {args.seed}. Times are UTC.")

    # 1. Generate the week.
    started = time.perf_counter()
    result = engine.generate(
        employees=list(scenario.employees),
        shifts=list(scenario.shifts),
        policy=scenario.policy,
        deterministic=True,
    )
    seconds = time.perf_counter() - started

    print(f"\n1. Weekly schedule: {result.status} in {seconds:.2f} s")
    if result.assignments is None:
        print("No schedule could be built for this restaurant. Try more staff or another seed.")
        return

    print_schedule(shifts, result.assignments)
    print()
    print_shortages(result, shifts_by_id)
    if result.validation_errors:
        print(f"Validation errors: {len(result.validation_errors)}")
    else:
        print("Independent validator: no rule violations.")

    # 2. Simulate a call-out. Some call-outs can't be covered at all (for
    # example, the only bartender that night). The demo shows the first one
    # the restaurant can recover from, and says how many it skipped.
    attempts = []
    repaired = None
    for callout_seed in range(args.seed, args.seed + 20):
        shift_id, employee_id = pick_callout(result.assignments, seed=callout_seed)
        if (shift_id, employee_id) in attempts:
            continue
        attempts.append((shift_id, employee_id))

        shift = shifts_by_id[shift_id]
        started = time.perf_counter()
        repaired = engine.repair(
            employees=apply_callout(scenario.employees, employee_id, shift),
            shifts=list(scenario.shifts),
            policy=scenario.policy,
            original_schedule=result.assignments,
            deterministic=True,
        )
        seconds = time.perf_counter() - started
        if repaired.assignments is not None:
            break

    role = _role_of(result.assignments, shift_id, employee_id)
    print("\n" + "=" * 60)
    print(f"2. Call-out: {_name(employee_id)} ({role}) calls in sick for "
          f"{_shift_label(shift)}")
    print("   and can't work again until 06:00 the next morning.")
    if len(attempts) > 1:
        print(f"   ({len(attempts) - 1} other call-out(s) tried first could not be covered "
              f"without breaking a hard minimum.)")

    # 3. Repair.
    print(f"\n3. Repair: {repaired.status} in {seconds:.2f} s")
    if repaired.assignments is None:
        print("This call-out makes a shift's hard minimum impossible to meet. "
              "The manager needs to step in.")
        return

    print_changes(result.assignments, repaired.assignments, shifts)
    print(f"\nAssignments changed: {repaired.assignment_changes}")
    print(f"Positions short: {_missing(result)} before, {_missing(repaired)} after.")
    if repaired.validation_errors:
        print(f"Validation errors: {len(repaired.validation_errors)}")
    else:
        print("Independent validator: no rule violations.")


if __name__ == "__main__":
    main()