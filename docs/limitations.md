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
- **Units:** maximum hours are stored in whole hours while targets are
  stored in minutes. Comparisons convert to minutes; a later cleanup may
  store both in minutes.

## Optimization results

- **Shortages are counted in positions, not minutes.** A missing server on
  a 4-hour shift and on an 8-hour shift each count as one.
- **FEASIBLE results are not proven optimal.** If a stage hits its time
  budget, the last valid schedule is kept. Shortages are only proven
  unavoidable when the coverage stage is OPTIMAL.

## Explanations

- **Lock conflict diagnostics** explain direct conflicts with positive
  locks only. Infeasibility caused by negative locks or combinations of
  constraints returns INFEASIBLE without a detailed explanation.
- **Infeasible repairs** (for example, a call-out that makes a hard
  staffing minimum impossible) are not yet explained to the manager.

## Testing and benchmarks

- **Synthetic data:** the random generator adjusts employee availability so
  shift minimums are reachable. Useful for controlled testing and
  benchmarks, but not a statistically representative sample of real
  restaurant staffing.
- **Small restaurants** (under about 18 staff) are often overloaded by the
  generated shift pattern and may be infeasible.
- **Benchmarks** were measured on a single laptop and depend on hardware.