# Benchmarks

Generation and call-out repair on synthetic restaurants
(`python -m scripts.benchmark`, 5 seeds per size).

- **Date:** 20 November 2026
- **Machine:** HP Laptop 14-ep0xxx, Intel Core i7-1355U (13th Gen), 16 GB RAM, Windows 11
- **Python:** 3.12.10

## Results

```
staff seed  load | generate     time short | repair       time short changes | check
------------------------------------------------------------------------------------
   18    0  0.87 | OPTIMAL     0.57s     8 | INFEASIBLE  0.02s     -       - | ok
   18    1  0.93 | OPTIMAL     0.17s     9 | OPTIMAL     0.14s    10       2 | ok
   18    2  0.90 | OPTIMAL     0.58s     4 | INFEASIBLE  0.02s     -       - | ok
   18    3  0.90 | OPTIMAL     0.21s     3 | OPTIMAL     0.18s     4       1 | ok
   18    4  0.89 | OPTIMAL     0.64s     4 | OPTIMAL     0.25s     4       2 | ok
   25    0  0.67 | OPTIMAL     0.56s     0 | OPTIMAL     0.32s     0       2 | ok
   25    1  0.73 | OPTIMAL     0.52s     2 | OPTIMAL     0.31s     2       2 | ok
   25    2  0.75 | OPTIMAL     0.80s     1 | OPTIMAL     0.33s     2       1 | ok
   25    3  0.67 | OPTIMAL     0.42s     3 | OPTIMAL     0.28s     3       2 | ok
   25    4  0.72 | OPTIMAL     0.67s     2 | OPTIMAL     0.36s     2       2 | ok
   40    0  0.76 | OPTIMAL     1.13s     4 | OPTIMAL     0.45s     4       2 | ok
   40    1  0.80 | OPTIMAL     1.93s     6 | OPTIMAL     0.41s     6       2 | ok
   40    2  0.86 | OPTIMAL     4.79s     6 | OPTIMAL     0.37s     7       1 | ok
   40    3  0.84 | OPTIMAL     1.53s     7 | OPTIMAL     0.43s     7       2 | ok
   40    4  0.83 | FEASIBLE    4.16s     6 | OPTIMAL     0.41s     6       2 | ok
```
| Staff | Generated | Repaired | Generate median / max | Repair median / max |
|------:|:---------:|:--------:|----------------------:|--------------------:|
|    18 |    5/5    |   3/5    |       0.57 s / 0.64 s |     0.14 s / 0.25 s |
|    25 |    5/5    |   5/5    |       0.56 s / 0.80 s |     0.32 s / 0.36 s |
|    40 |    5/5    |   5/5    |       1.93 s / 4.79 s |     0.41 s / 0.45 s |

## Observations

- Every returned schedule passed independent validation.
- Call-out repairs finished in under 0.5 s and changed at most 2 assignments.
- One 40-staff run returned FEASIBLE: a later optimization stage hit its
  time budget, and the last valid schedule was kept.
- At 18 staff, 2 of 5 call-outs made a hard staffing minimum impossible,
  so repair returned INFEASIBLE. A future conflict explanation should tell
  the manager which shift and role cannot be covered.
- Timings depend on hardware. Results use synthetic data (see
  `docs/limitations.md`).