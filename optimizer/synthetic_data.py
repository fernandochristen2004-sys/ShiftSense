"""Reproducible synthetic restaurant scheduling scenarios.

Generates single-location restaurant scenarios with mixed roles,
multi-skilled employees, full-time and part-time availability,
weekend demand and overnight closing shifts.

Two modes:
  - "random": a realistic restaurant week. After generating staff, the
    generator extends some availability so each shift's minimum staffing
    can be met by distinct people without obvious overlap, rest or hour
    conflicts. This makes scenarios of about 18+ employees reliably
    solvable in practice, but it is a greedy construction, not a proof.
    Small restaurants (under about 18 employees) are often overloaded
    and may still be infeasible.
  - "feasible": a simple scenario with a known fully covered reference
    schedule (one dedicated employee per shift). Useful as a sanity
    check, not as a realistic workload.

The load ratio is an approximate capacity indicator, not proof that
staffing requirements can be satisfied.

All times are UTC.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from random import Random

from optimizer.models import (
    DateTimeShift,
    Employee,
    SchedulingPolicy,
    ShiftRequirement,
)

ROLE_SHARES = (
    ("server", 0.40),
    ("cook", 0.30),
    ("host", 0.15),
    ("bartender", 0.15),
)

# A plausible second skill for each primary role.
SECOND_SKILL = {
    "server": "host",
    "host": "server",
    "cook": "server",
    "bartender": "server",
}

FRIDAY, SATURDAY = 4, 5
MIN_EMPLOYEES = 8  # At least two people per role.

# Daily shift pattern (hours past midnight; 24 or more means the next day).
LUNCH = (11, 15)
DINNER = (17, 23)
LATE_CLOSE = (23, 26)  # Friday and Saturday only; starts when dinner ends.


@dataclass(frozen=True)
class RestaurantScenario:
    employees: tuple[Employee, ...]
    shifts: tuple[DateTimeShift, ...]
    policy: SchedulingPolicy
    seed: int
    demand_minutes: int
    capacity_minutes: int
    reference_schedule: dict[int, dict[str, list[int]]] | None = None

    @property
    def load_ratio(self) -> float:
        """Staffing demand divided by staff capacity (below 1.0 is easier)."""
        if self.capacity_minutes == 0:
            return float("inf")
        return self.demand_minutes / self.capacity_minutes


def _at(day: date, hour: int) -> datetime:
    """UTC datetime on `day`. Hours of 24 or more roll into the next day."""
    midnight = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
    return midnight + timedelta(hours=hour)


def _is_weekend_night(day: date) -> bool:
    return day.weekday() in (FRIDAY, SATURDAY)


def _minutes_between(earlier: datetime, later: datetime) -> int:
    return int((later - earlier).total_seconds() // 60)


def _availability_minutes(intervals: tuple[tuple[datetime, datetime], ...]) -> int:
    return sum(_minutes_between(start, end) for start, end in intervals)


def _default_policy() -> SchedulingPolicy:
    # Lunch 11-15 + dinner 17-23 is a valid split (2 h break, 12 h span).
    # A 02:00 close followed by an 11:00 lunch is blocked (9 h rest, 16 h span).
    return SchedulingPolicy(
        minimum_rest_hours=11,
        enforce_minimum_rest=True,
        allow_split_shifts=True,
        split_shift_min_break_minutes=120,
        max_split_span_minutes=780,
        fairness_enabled=True,
        allow_partial_coverage=True,
    )


def _role_counts(employee_count: int) -> dict[str, int]:
    """Allocate employees by role, guaranteeing at least two per role."""
    counts = {role: 2 for role, _ in ROLE_SHARES}

    remaining = employee_count - sum(counts.values())

    # Distribute remaining employees according to role shares.
    for _ in range(remaining):
        role = max(
            ROLE_SHARES,
            key=lambda item: (
                employee_count * item[1] - counts[item[0]],
                item[1],
            ),
        )[0]
        counts[role] += 1

    return counts


def _one_person_can_work_both(
    a: DateTimeShift,
    b: DateTimeShift,
    policy: SchedulingPolicy,
) -> bool:
    """Whether one employee could legally work both shifts under `policy`.

    Mirrors the engine's overlap, minimum-rest and split-shift rules.
    """
    first, second = (a, b) if a.starts_at <= b.starts_at else (b, a)
    gap = _minutes_between(first.ends_at, second.starts_at)

    if gap < 0:
        return False
    if not policy.enforce_minimum_rest:
        return True
    if gap >= policy.minimum_rest_hours * 60:
        return True
    return (
        policy.allow_split_shifts
        and gap >= policy.split_shift_min_break_minutes
        and _minutes_between(first.starts_at, second.ends_at)
        <= policy.max_split_span_minutes
    )


def _ensure_minimum_availability(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    policy: SchedulingPolicy,
    rng: Random,
) -> list[Employee]:
    """Extend availability so each shift's minimum can be met by distinct people.

    Shifts are processed in time order and a plausible crew is picked for
    each one. A person is skipped for a shift if they were already picked
    for a conflicting shift (overlap or too little rest), already fill
    another role in this shift, or would go over their maximum hours.
    When too few available people remain, the shift is added to other
    qualified employees' availability.

    This is a greedy construction that makes infeasible scenarios much
    rarer. It is not a proof of feasibility.
    """
    employees = list(employees)
    chosen_by_shift: dict[int, set[int]] = {}
    minutes_chosen = [0] * len(employees)

    for shift in sorted(shifts, key=lambda s: s.starts_at):
        shift_minutes = _minutes_between(shift.starts_at, shift.ends_at)

        def is_available(employee: Employee) -> bool:
            return any(
                start <= shift.starts_at and shift.ends_at <= end
                for start, end in employee.datetime_availability
            )

        # People who cannot also work this shift.
        conflicting: set[int] = set()
        for other in shifts:
            if other.id in chosen_by_shift and not _one_person_can_work_both(
                shift, other, policy
            ):
                conflicting |= chosen_by_shift[other.id]

        def within_hours(index: int) -> bool:
            limit = employees[index].max_hours * 60
            return minutes_chosen[index] + shift_minutes <= limit

        chosen_here: set[int] = set()

        # Fill the hardest roles first (fewest qualified people).
        requirements = sorted(
            shift.requirements,
            key=lambda r: sum(1 for e in employees if r.skill in e.skills),
        )

        for requirement in requirements:
            qualified = [
                index for index, employee in enumerate(employees)
                if requirement.skill in employee.skills
                and index not in conflicting
                and index not in chosen_here
            ]
            # Prefer people with hours to spare; fall back to everyone else
            # only if needed, so small restaurants still get availability.
            preferred = [i for i in qualified if within_hours(i)]
            fallback = [i for i in qualified if not within_hours(i)]

            picked: list[int] = []
            for pool in (preferred, fallback):
                missing = requirement.min_count - len(picked)
                if missing <= 0:
                    break

                available = [i for i in pool if is_available(employees[i])]
                # Spread work around; keep multi-skilled staff free when possible.
                available.sort(key=lambda i: (minutes_chosen[i], len(employees[i].skills)))
                picked += available[:missing]

                missing = requirement.min_count - len(picked)
                if missing <= 0:
                    break

                candidates = [i for i in pool if not is_available(employees[i])]
                rng.shuffle(candidates)
                candidates.sort(key=lambda i: minutes_chosen[i])

                for index in candidates[:missing]:
                    employee = employees[index]
                    employees[index] = replace(
                        employee,
                        datetime_availability=tuple(sorted(
                            employee.datetime_availability
                            + ((shift.starts_at, shift.ends_at),)
                        )),
                    )
                    picked.append(index)

            chosen_here.update(picked)

        for index in chosen_here:
            minutes_chosen[index] += shift_minutes
        chosen_by_shift[shift.id] = chosen_here

    return employees


def _generate_feasible_scenario(
    employee_count: int,
    days: int,
    seed: int,
    start_date: date,
) -> RestaurantScenario:
    """Build a restaurant with a known fully covered schedule."""

    rng = Random(seed)
    dates = [
        start_date + timedelta(days=day_index)
        for day_index in range(days)
    ]

    # Reuse the restaurant's lunch, dinner and late-close patterns.
    templates = []

    for current_date in dates:
        templates.append((current_date, *LUNCH))
        templates.append((current_date, *DINNER))

        if _is_weekend_night(current_date):
            templates.append((current_date, *LATE_CLOSE))

    # Each shift needs at least one employee.
    if employee_count < len(templates):
        raise ValueError(
            "Feasible mode requires at least one employee "
            "per generated shift."
        )

    roles = tuple(role for role, _ in ROLE_SHARES)

    shifts = []
    employees = []
    reference_schedule = {}
    demand_minutes = 0

    # Assign one dedicated employee to each shift.
    # This deliberately guarantees no overlap or rest conflicts.
    for shift_id, (current_date, start_hour, end_hour) in enumerate(
        templates,
        start=1,
    ):
        role = roles[(shift_id - 1) % len(roles)]

        start = _at(current_date, start_hour)
        end = _at(current_date, end_hour)
        minutes = _minutes_between(start, end)

        shifts.append(
            DateTimeShift(
                id=shift_id,
                starts_at=start,
                ends_at=end,
                requirements=(
                    ShiftRequirement(
                        skill=role,
                        count=1,
                        min_count=1,
                    ),
                ),
            )
        )

        employees.append(
            Employee(
                id=shift_id,
                name=f"Employee {shift_id}",
                skills=frozenset({role}),
                max_hours=40,
                datetime_availability=((start, end),),
                target_minutes=minutes,
            )
        )

        reference_schedule[shift_id] = {
            role: [shift_id],
        }

        demand_minutes += minutes

    # Additional employees provide spare scheduling capacity.
    for employee_id in range(len(templates) + 1, employee_count + 1):
        role = rng.choice(roles)

        availability = tuple(
            (_at(current_date, 10), _at(current_date, 26))
            for current_date in dates
        )

        employees.append(
            Employee(
                id=employee_id,
                name=f"Employee {employee_id}",
                skills=frozenset({role}),
                max_hours=40,
                datetime_availability=availability,
                target_minutes=None,
            )
        )

    capacity_minutes = sum(
        min(
            employee.max_hours * 60,
            _availability_minutes(employee.datetime_availability),
        )
        for employee in employees
    )

    return RestaurantScenario(
        employees=tuple(employees),
        shifts=tuple(shifts),
        policy=_default_policy(),
        seed=seed,
        demand_minutes=demand_minutes,
        capacity_minutes=capacity_minutes,
        reference_schedule=reference_schedule,
    )


def generate_restaurant_scenario(
    employee_count: int,
    days: int = 7,
    seed: int = 42,
    start_date: date = date(2026, 11, 23),
    mode: str = "random",
) -> RestaurantScenario:
    """Generate a reproducible restaurant scheduling scenario."""

    if type(employee_count) is not int or employee_count < MIN_EMPLOYEES:
        raise ValueError(f"Employee count must be an integer of at least {MIN_EMPLOYEES}.")
    if type(days) is not int or days < 1:
        raise ValueError("Days must be a positive integer.")
    if type(seed) is not int:
        raise ValueError("Seed must be an integer.")
    if type(start_date) is not date:
        raise ValueError("Start date must be a date.")
    if mode not in ("random", "feasible"):
        raise ValueError("Mode must be 'random' or 'feasible'.")

    if mode == "feasible":
        return _generate_feasible_scenario(
            employee_count=employee_count,
            days=days,
            seed=seed,
            start_date=start_date,
        )

    rng = Random(seed)
    dates = [start_date + timedelta(days=i) for i in range(days)]

    # Employees
    role_list = [
        role
        for role, count in _role_counts(employee_count).items()
        for _ in range(count)
    ]
    rng.shuffle(role_list)

    employees: list[Employee] = []

    for employee_id, role in enumerate(role_list, start=1):
        skills = {role}
        if rng.random() < 0.25:
            skills.add(SECOND_SKILL[role])

        if rng.random() < 0.40:
            # Full-time: works most days, can close on weekend nights.
            days_off = set(rng.sample(range(days), k=min(1, days - 1)))
            work_days = [d for i, d in enumerate(dates) if i not in days_off]
            availability = tuple(
                (_at(d, 10), _at(d, 26 if _is_weekend_night(d) else 24))
                for d in work_days
            )
            max_hours = 40
            target_minutes = rng.choice((32, 36, 40)) * 60
        else:
            # Part-time: a few days, in a lunch, evening or all-day window.
            work_days = sorted(rng.sample(dates, k=min(days, rng.randint(3, 5))))
            start_hour, end_hour = rng.choice(((10, 16), (16, 26), (10, 26)))
            availability = tuple(
                (_at(d, start_hour), _at(d, end_hour)) for d in work_days
            )
            max_hours = 25
            target_minutes = (
                None if rng.random() < 0.20 else rng.choice((12, 16, 20, 24)) * 60
            )

        employees.append(
            Employee(
                id=employee_id,
                name=f"Employee {employee_id}",
                skills=frozenset(skills),
                max_hours=max_hours,
                datetime_availability=availability,
                target_minutes=target_minutes,
            )
        )

    # Shifts (staffing scales with restaurant size; 20 employees is the baseline)
    scale = employee_count / 20

    def staff(base: int, essential: bool = True) -> int:
        """Scale a baseline crew size. Small restaurants can drop optional roles."""
        count = round(base * scale)
        return max(1, count) if essential else count

    shifts: list[DateTimeShift] = []
    demand_minutes = 0
    shift_id = 1

    for d in dates:
        weekend = _is_weekend_night(d)
        templates = [
            (*LUNCH, {
                "cook": staff(2),
                "server": staff(2),
                "host": staff(1, essential=False),
            }),
            (*DINNER, {
                "cook": staff(3 if weekend else 2),
                "server": staff(4 if weekend else 3),
                "host": staff(2 if weekend else 1, essential=False),
                "bartender": staff(2 if weekend else 1, essential=False),
            }),
        ]
        if weekend:
            # Late close after dinner ends, crossing midnight. Starting it
            # when dinner ends keeps the two crews from overlapping.
            templates.append((*LATE_CLOSE, {
                "server": staff(1),
                "bartender": staff(1, essential=False),
            }))

        for start_hour, end_hour, needs in templates:
            # Optional roles scaled down to zero are left out entirely.
            needs = {role: count for role, count in needs.items() if count > 0}

            requirements = tuple(
                ShiftRequirement(
                    skill=role,
                    count=count,
                    # Any role can run one short when it needs more than one person.
                    min_count=count - 1 if count > 1 else count,
                )
                for role, count in needs.items()
            )
            shifts.append(
                DateTimeShift(
                    id=shift_id,
                    starts_at=_at(d, start_hour),
                    ends_at=_at(d, end_hour),
                    requirements=requirements,
                )
            )
            demand_minutes += (end_hour - start_hour) * 60 * sum(needs.values())
            shift_id += 1

    policy = _default_policy()

    employees = _ensure_minimum_availability(employees, shifts, policy, rng)

    capacity_minutes = sum(
        min(employee.max_hours * 60, _availability_minutes(employee.datetime_availability))
        for employee in employees
    )

    return RestaurantScenario(
        employees=tuple(employees),
        shifts=tuple(shifts),
        policy=policy,
        seed=seed,
        demand_minutes=demand_minutes,
        capacity_minutes=capacity_minutes,
    )


def pick_callout(
    assignments: dict[int, dict[str, list[int]]],
    seed: int,
) -> tuple[int, int]:
    """Pick one (shift_id, employee_id) assignment to simulate an absence."""
    assigned = sorted(
        (shift_id, employee_id)
        for shift_id, roles in assignments.items()
        for employee_ids in roles.values()
        for employee_id in employee_ids
    )
    if not assigned:
        raise ValueError("Schedule has no assignments to call out.")
    return Random(seed).choice(assigned)
