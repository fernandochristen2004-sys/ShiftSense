"""Speed check and end-to-end run on synthetic restaurants.

For each restaurant size and seed:
  1. generate a weekly schedule,
  2. pick one assigned employee and simulate a call-out for that shift,
  3. repair the schedule,
  4. record time, status, missing positions, changes and validation.

Run from the project root:
    python -m scripts.benchmark
    python -m scripts.benchmark --sizes 25 40 --seeds 10
    python -m scripts.benchmark --deterministic   (repeatable, slower)

A repair can be INFEASIBLE when the call-out makes a hard minimum
impossible (common in small, overloaded restaurants). That is reported,
not treated as a failure.

Exits with code 1 if any returned schedule has validation errors or the
called-out employee is still on their shift, so it can also be used in CI.
"""

import argparse
import statistics
import sys
import time

from optimizer import engine
from optimizer.synthetic_data import (
    apply_callout,
    generate_restaurant_scenario,
    pick_callout,
)


def _missing(result) -> int | None:
    """Total missing positions, or None if no schedule was returned."""
    if result.assignments is None:
        return None
    return sum(shortage.missing for shortage in result.shortages)


def _timed(function, **kwargs):
    start = time.perf_counter()
    result = function(**kwargs)
    return result, time.perf_counter() - start


def run_once(size: int, seed: int, deterministic: bool = False) -> dict:
    scenario = generate_restaurant_scenario(size, seed=seed)
    shifts = list(scenario.shifts)

    generated, generate_seconds = _timed(
        engine.generate,
        employees=list(scenario.employees),
        shifts=shifts,
        policy=scenario.policy,
        deterministic=deterministic,
    )

    row = {
        "size": size,
        "seed": seed,
        "load": scenario.load_ratio,
        "gen_status": generated.status,
        "gen_seconds": generate_seconds,
        "gen_missing": _missing(generated),
        "rep_status": None,
        "rep_seconds": None,
        "rep_missing": None,
        "changes": None,
        "problems": [],
    }

    if generated.validation_errors:
        row["problems"].append(f"generate: {len(generated.validation_errors)} validation errors")

    if generated.assignments is None:
        return row

    # Simulate a call-out on one assigned shift, then repair.
    shift_id, employee_id = pick_callout(generated.assignments, seed=seed)
    shift = next(s for s in shifts if s.id == shift_id)
    employees = apply_callout(scenario.employees, employee_id, shift)

    repaired, repair_seconds = _timed(
        engine.repair,
        employees=employees,
        shifts=shifts,
        policy=scenario.policy,
        original_schedule=generated.assignments,
        deterministic=deterministic,
    )

    row.update(
        rep_status=repaired.status,
        rep_seconds=repair_seconds,
        rep_missing=_missing(repaired),
        changes=repaired.assignment_changes,
    )

    if repaired.validation_errors:
        row["problems"].append(f"repair: {len(repaired.validation_errors)} validation errors")

    if repaired.assignments is not None:
        still_assigned = any(
            employee_id in ids
            for ids in repaired.assignments.get(shift_id, {}).values()
        )
        if still_assigned:
            row["problems"].append("called-out employee still assigned")

    return row


def _fmt(value, spec: str = "") -> str:
    return "-" if value is None else format(value, spec)


def print_table(rows: list[dict]) -> None:
    header = (
        f"{'staff':>5} {'seed':>4} {'load':>5} | "
        f"{'generate':<10} {'time':>6} {'short':>5} | "
        f"{'repair':<10} {'time':>6} {'short':>5} {'changes':>7} | check"
    )
    print(header)
    print("-" * len(header))

    for r in rows:
        print(
            f"{r['size']:>5} {r['seed']:>4} {r['load']:>5.2f} | "
            f"{r['gen_status']:<10} {_fmt(r['gen_seconds'], '.2f'):>5}s {_fmt(r['gen_missing']):>5} | "
            f"{_fmt(r['rep_status']):<10} {_fmt(r['rep_seconds'], '.2f'):>5}s "
            f"{_fmt(r['rep_missing']):>5} {_fmt(r['changes']):>7} | "
            f"{'; '.join(r['problems']) or 'ok'}"
        )


def print_summary(rows: list[dict]) -> None:
    print()
    print("Summary (seconds)")
    for size in sorted({r["size"] for r in rows}):
        group = [r for r in rows if r["size"] == size]
        gen = [r["gen_seconds"] for r in group]
        rep = [r["rep_seconds"] for r in group if r["rep_seconds"] is not None]
        solved = sum(r["gen_status"] in ("OPTIMAL", "FEASIBLE") for r in group)

        attempted = [r for r in group if r["rep_status"] is not None]
        repaired = sum(r["rep_status"] in ("OPTIMAL", "FEASIBLE") for r in attempted)

        line = (
            f"  {size:>3} staff: generated {solved}/{len(group)}, "
            f"repaired {repaired}/{len(attempted)}, "
            f"generate median {statistics.median(gen):.2f} max {max(gen):.2f}"
        )
        if rep:
            line += f", repair median {statistics.median(rep):.2f} max {max(rep):.2f}"
        print(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="+", default=[18, 25, 40])
    parser.add_argument("--seeds", type=int, default=5, help="number of seeds per size")
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="single-threaded, repeatable runs (slower; times are not comparable)",
    )
    args = parser.parse_args(argv)

    rows = [
        run_once(size, seed, args.deterministic)
        for size in args.sizes
        for seed in range(args.seeds)
    ]

    print_table(rows)
    print_summary(rows)

    failed = [r for r in rows if r["problems"]]
    if failed:
        print(f"\n{len(failed)} run(s) had problems.")
        return 1

    print("\nAll returned schedules passed validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
