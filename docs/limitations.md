# Known limitations

ShiftSense is a portfolio project in active development. These are known
boundaries of the current scheduling engine.

## Scheduling rules

- **Labor law:** rest, split-shift and hour rules are configurable product
  policies, not verified legal compliance for any jurisdiction.
- **Daylight saving time:** handling is conservative. Ambiguous or
  nonexistent local times are rejected rather than resolved automatically.
- **Maximum hours** apply within the planning window. Outside (fixed)
  assignments are checked for overlap and rest, but do not count toward
  the employee's maximum hours.
- **Units:** maximum hours and minimum rest are stored in whole hours, while
  targets are stored in minutes. Comparisons convert to minutes; a later
  cleanup may store everything in minutes.

## Optimization results

- **Shortages are counted in positions, not minutes.** A missing server on
  a 4-hour shift and on an 8-hour shift each count as one.
- **FEASIBLE results are not proven optimal.** If a stage hits its time
  budget, the last valid schedule is kept. Shortages are only proven
  unavoidable when the coverage stage is OPTIMAL.
- **Results can vary between runs by default.** CP-SAT searches in parallel, so when
  several schedules are equally good, which one is returned can differ. Statuses and
  objective values are stable. Pass `deterministic=True` (used by the demo) for
  repeatable results; it is slower, especially for larger restaurants.

## Explanations

- **Lock conflict diagnostics** explain direct conflicts with positive
  locks only. Infeasibility caused by negative locks or combinations of
  constraints returns INFEASIBLE without a detailed explanation.
- **"Why no fix" explanations check one person at a time.** For each gap,
  they list everyone with the right skill and the first rule that keeps
  them out of the current schedule. When each gap has someone free on its
  own but the gaps can't all be filled together, the explanation says so
  but doesn't name the exact conflict. CP-SAT can report conflicting
  constraints (assumptions / sufficient assumptions for infeasibility);
  using that would give exact explanations.

## Testing and benchmarks

- **Synthetic data:** the random generator adjusts employee availability so
  shift minimums are reachable. Useful for controlled testing and
  benchmarks, but not a statistically representative sample of real
  restaurant staffing.
- **Small restaurants** (under about 18 staff) are often overloaded by the
  generated shift pattern and may be infeasible.
- **Benchmarks** were measured on a single laptop and depend on hardware.
- **Simulated call-outs** block the employee from the start of the shift until
  06:00 the next morning. Some call-outs therefore cannot be covered, and repair
  returns INFEASIBLE.