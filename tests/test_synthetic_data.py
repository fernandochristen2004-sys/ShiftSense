"""Tests for the synthetic restaurant scenario generator."""

from datetime import date, datetime, timedelta, timezone

import pytest

from optimizer.models import DateTimeShift, ShiftRequirement
from optimizer.synthetic_data import (
    MIN_EMPLOYEES,
    ROLE_SHARES,
    RestaurantScenario,
    _one_person_can_work_both,
    _role_counts,
    apply_callout,
    generate_restaurant_scenario,
    pick_callout,
)
from optimizer.validator import validate_schedule

ROLES = {role for role, _ in ROLE_SHARES}
MONDAY = date(2026, 11, 23)


def _available(employee, shift):
    return any(
        start <= shift.starts_at and shift.ends_at <= end
        for start, end in employee.datetime_availability
    )


# Reproducibility

def test_same_seed_produces_identical_scenario():
    first = generate_restaurant_scenario(20, seed=7)
    second = generate_restaurant_scenario(20, seed=7)

    assert first == second


def test_different_seeds_produce_different_employees():
    first = generate_restaurant_scenario(20, seed=1)
    second = generate_restaurant_scenario(20, seed=2)

    assert first.employees != second.employees


def test_scenario_records_its_seed():
    assert generate_restaurant_scenario(20, seed=99).seed == 99


# Input validation

@pytest.mark.parametrize("employee_count", [MIN_EMPLOYEES - 1, 0, -5, True, 10.0, "10"])
def test_rejects_invalid_employee_count(employee_count):
    with pytest.raises(ValueError):
        generate_restaurant_scenario(employee_count)


@pytest.mark.parametrize("days", [0, -1, True, 7.0, "7"])
def test_rejects_invalid_days(days):
    with pytest.raises(ValueError):
        generate_restaurant_scenario(20, days=days)


@pytest.mark.parametrize("seed", [1.5, "42", None, True])
def test_rejects_invalid_seed(seed):
    with pytest.raises(ValueError):
        generate_restaurant_scenario(20, seed=seed)


@pytest.mark.parametrize(
    "start_date",
    ["2026-11-23", datetime(2026, 11, 23, tzinfo=timezone.utc), None],
)
def test_rejects_invalid_start_date(start_date):
    with pytest.raises(ValueError):
        generate_restaurant_scenario(20, start_date=start_date)


@pytest.mark.parametrize("mode", ["", "Random", "realistic", None])
def test_rejects_invalid_mode(mode):
    with pytest.raises(ValueError):
        generate_restaurant_scenario(20, mode=mode)


def test_accepts_minimum_employee_count():
    scenario = generate_restaurant_scenario(MIN_EMPLOYEES)

    assert len(scenario.employees) == MIN_EMPLOYEES


# Role allocation

@pytest.mark.parametrize("employee_count", range(MIN_EMPLOYEES, 61))
def test_role_counts_sum_and_minimum(employee_count):
    counts = _role_counts(employee_count)

    assert set(counts) == ROLES
    assert sum(counts.values()) == employee_count
    assert all(count >= 2 for count in counts.values())


@pytest.mark.parametrize("employee_count", [8, 10, 25, 40])
def test_every_role_has_at_least_two_qualified_employees(employee_count):
    scenario = generate_restaurant_scenario(employee_count)

    for role in ROLES:
        qualified = [e for e in scenario.employees if role in e.skills]
        assert len(qualified) >= 2, role


# Employees

@pytest.mark.parametrize("employee_count", [10, 25, 40])
def test_employee_ids_are_unique_and_count_matches(employee_count):
    scenario = generate_restaurant_scenario(employee_count)
    ids = [e.id for e in scenario.employees]

    assert len(ids) == employee_count
    assert len(set(ids)) == employee_count


def test_employees_have_one_or_two_known_skills():
    scenario = generate_restaurant_scenario(40)

    for employee in scenario.employees:
        assert 1 <= len(employee.skills) <= 2
        assert employee.skills <= ROLES


def test_some_employees_are_multi_skilled():
    scenario = generate_restaurant_scenario(40)

    assert any(len(e.skills) == 2 for e in scenario.employees)


def test_targets_never_exceed_maximum_hours():
    for seed in range(10):
        scenario = generate_restaurant_scenario(25, seed=seed)
        for employee in scenario.employees:
            if employee.target_minutes is not None:
                assert 0 <= employee.target_minutes <= employee.max_hours * 60


def test_some_employees_have_no_target_across_seeds():
    has_untargeted = any(
        e.target_minutes is None
        for seed in range(10)
        for e in generate_restaurant_scenario(25, seed=seed).employees
    )

    assert has_untargeted


def test_availability_intervals_are_valid_utc_and_sorted():
    scenario = generate_restaurant_scenario(25)

    for employee in scenario.employees:
        intervals = employee.datetime_availability
        assert intervals
        assert list(intervals) == sorted(intervals)
        for start, end in intervals:
            assert start.tzinfo == timezone.utc
            assert end.tzinfo == timezone.utc
            assert end > start


def test_some_availability_crosses_midnight():
    scenario = generate_restaurant_scenario(25)

    assert any(
        end.date() > start.date()
        for e in scenario.employees
        for start, end in e.datetime_availability
    )


# Shifts

def test_shift_ids_are_unique_and_sequential():
    scenario = generate_restaurant_scenario(20)
    ids = [s.id for s in scenario.shifts]

    assert ids == list(range(1, len(ids) + 1))


def test_week_from_monday_has_lunch_dinner_and_weekend_closes():
    scenario = generate_restaurant_scenario(20, days=7, start_date=MONDAY)

    # 7 lunches + 7 dinners + Friday and Saturday closes.
    assert len(scenario.shifts) == 16


def test_shifts_are_utc_and_end_after_start():
    scenario = generate_restaurant_scenario(20)

    for shift in scenario.shifts:
        assert shift.starts_at.tzinfo == timezone.utc
        assert shift.ends_at > shift.starts_at


def test_weekend_close_starts_after_dinner_and_crosses_midnight():
    scenario = generate_restaurant_scenario(20, days=7, start_date=MONDAY)
    overnight = [s for s in scenario.shifts if s.ends_at.date() > s.starts_at.date()]

    assert len(overnight) == 2
    assert {s.starts_at.weekday() for s in overnight} == {4, 5}  # Friday, Saturday
    for shift in overnight:
        assert shift.starts_at.hour == 23
        assert shift.ends_at - shift.starts_at == timedelta(hours=3)


@pytest.mark.parametrize("employee_count", [8, 20, 40])
def test_shifts_never_overlap(employee_count):
    shifts = sorted(
        generate_restaurant_scenario(employee_count).shifts,
        key=lambda s: s.starts_at,
    )

    for earlier, later in zip(shifts, shifts[1:]):
        assert earlier.ends_at <= later.starts_at


def test_weekend_dinner_needs_more_staff_than_weekday_dinner():
    scenario = generate_restaurant_scenario(20, days=7, start_date=MONDAY)
    dinners = [s for s in scenario.shifts if s.starts_at.hour == 17]

    def total(shift):
        return sum(r.count for r in shift.requirements)

    monday_dinner = next(s for s in dinners if s.starts_at.weekday() == 0)
    saturday_dinner = next(s for s in dinners if s.starts_at.weekday() == 5)

    assert total(saturday_dinner) > total(monday_dinner)


def test_requirements_have_valid_minimums():
    scenario = generate_restaurant_scenario(40)

    for shift in scenario.shifts:
        skills = [r.skill for r in shift.requirements]
        assert len(skills) == len(set(skills))
        for requirement in shift.requirements:
            assert requirement.skill in ROLES
            assert 1 <= requirement.min_count <= requirement.count
            expected_min = requirement.count - 1 if requirement.count > 1 else 1
            assert requirement.min_count == expected_min


def test_some_requirements_allow_one_short():
    scenario = generate_restaurant_scenario(20)

    assert any(
        r.min_count == r.count - 1
        for s in scenario.shifts
        for r in s.requirements
    )


@pytest.mark.parametrize("employee_count", [8, 20, 40])
def test_every_shift_needs_a_cook_and_a_server_or_closer(employee_count):
    scenario = generate_restaurant_scenario(employee_count)

    for shift in scenario.shifts:
        skills = {r.skill for r in shift.requirements}
        assert "server" in skills
        if shift.starts_at.hour != 23:  # The late close has no kitchen.
            assert "cook" in skills


def test_small_restaurant_can_drop_optional_lunch_host():
    small = generate_restaurant_scenario(8, days=7, start_date=MONDAY)
    lunches = [s for s in small.shifts if s.starts_at.hour == 11]

    assert all("host" not in {r.skill for r in s.requirements} for s in lunches)


def test_staffing_grows_with_restaurant_size():
    small = generate_restaurant_scenario(10)
    large = generate_restaurant_scenario(40)

    assert large.demand_minutes > small.demand_minutes


# Availability guarantee

@pytest.mark.parametrize("employee_count", [8, 10, 15, 25, 40, 60])
@pytest.mark.parametrize("seed", range(5))
def test_every_shift_minimum_can_be_met_by_distinct_people(employee_count, seed):
    """Within a shift, each person fills one role, so count distinct people."""
    scenario = generate_restaurant_scenario(employee_count, seed=seed)

    for shift in scenario.shifts:
        used = set()
        requirements = sorted(
            shift.requirements,
            key=lambda r: sum(1 for e in scenario.employees if r.skill in e.skills),
        )
        for requirement in requirements:
            free = [
                e.id for e in scenario.employees
                if requirement.skill in e.skills
                and e.id not in used
                and _available(e, shift)
            ]
            assert len(free) >= requirement.min_count, (shift.id, requirement.skill)
            # Reserve single-skill people first, like a manager would.
            free.sort(key=lambda i: len(next(e for e in scenario.employees if e.id == i).skills))
            used.update(free[:requirement.min_count])


# Compatibility helper

def _shift(day, start_hour, end_hour):
    midnight = datetime(2026, 11, 23 + day, tzinfo=timezone.utc)
    return DateTimeShift(
        id=start_hour,
        starts_at=midnight + timedelta(hours=start_hour),
        ends_at=midnight + timedelta(hours=end_hour),
        requirements=(ShiftRequirement("server", 1),),
    )


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (_shift(0, 11, 15), _shift(0, 17, 23), True),   # lunch + dinner split
        (_shift(0, 17, 23), _shift(0, 23, 26), False),  # dinner then close, no break
        (_shift(0, 17, 23), _shift(0, 20, 26), False),  # overlap
        (_shift(0, 23, 26), _shift(1, 11, 15), False),  # 02:00 close, 11:00 lunch
        (_shift(0, 23, 26), _shift(1, 17, 23), True),   # 15 h rest
        (_shift(0, 17, 23), _shift(1, 11, 15), True),   # 12 h rest
    ],
)
def test_one_person_can_work_both(a, b, expected):
    policy = generate_restaurant_scenario(20).policy

    assert _one_person_can_work_both(a, b, policy) is expected
    assert _one_person_can_work_both(b, a, policy) is expected


# Policy

def test_policy_enables_realistic_rules():
    policy = generate_restaurant_scenario(20).policy

    assert policy.enforce_minimum_rest is True
    assert policy.minimum_rest_hours == 11
    assert policy.allow_split_shifts is True
    assert policy.allow_partial_coverage is True
    assert policy.fairness_enabled is True


# Demand, capacity and load ratio

def test_demand_minutes_matches_shift_requirements():
    scenario = generate_restaurant_scenario(25)
    expected = sum(
        int((s.ends_at - s.starts_at).total_seconds() // 60)
        * sum(r.count for r in s.requirements)
        for s in scenario.shifts
    )

    assert scenario.demand_minutes == expected


def test_capacity_respects_maximum_hours_and_availability():
    scenario = generate_restaurant_scenario(25)
    expected = sum(
        min(
            e.max_hours * 60,
            sum(
                int((end - start).total_seconds() // 60)
                for start, end in e.datetime_availability
            ),
        )
        for e in scenario.employees
    )

    assert scenario.capacity_minutes == expected


@pytest.mark.parametrize("employee_count", [10, 25, 40])
def test_load_ratio_is_positive_and_finite(employee_count):
    ratio = generate_restaurant_scenario(employee_count).load_ratio

    assert 0 < ratio < float("inf")


def test_load_ratio_is_infinite_without_capacity():
    scenario = RestaurantScenario(
        employees=(),
        shifts=(),
        policy=generate_restaurant_scenario(20).policy,
        seed=0,
        demand_minutes=100,
        capacity_minutes=0,
    )

    assert scenario.load_ratio == float("inf")


# Feasible mode

def test_feasible_scenario_has_valid_reference_schedule():
    scenario = generate_restaurant_scenario(
        employee_count=25,
        days=7,
        seed=42,
        mode="feasible",
    )

    assert scenario.reference_schedule is not None

    errors = validate_schedule(
        employees=list(scenario.employees),
        shifts=list(scenario.shifts),
        schedule=scenario.reference_schedule,
        policy=scenario.policy,
    )

    assert errors == []


def test_feasible_mode_needs_one_employee_per_shift():
    # A 7-day week has 16 shifts.
    with pytest.raises(ValueError):
        generate_restaurant_scenario(15, days=7, start_date=MONDAY, mode="feasible")


def test_random_mode_has_no_reference_schedule():
    assert generate_restaurant_scenario(20).reference_schedule is None


# Call-out helper

SAMPLE_ASSIGNMENTS = {
    1: {"cook": [1, 2], "server": [3]},
    2: {"server": [4]},
}


def test_pick_callout_returns_an_existing_assignment():
    shift_id, employee_id = pick_callout(SAMPLE_ASSIGNMENTS, seed=3)

    assert any(
        employee_id in ids for ids in SAMPLE_ASSIGNMENTS[shift_id].values()
    )


def test_pick_callout_is_reproducible():
    assert pick_callout(SAMPLE_ASSIGNMENTS, seed=5) == pick_callout(SAMPLE_ASSIGNMENTS, seed=5)


def test_pick_callout_ignores_dictionary_order():
    reordered = {2: {"server": [4]}, 1: {"server": [3], "cook": [1, 2]}}

    assert pick_callout(SAMPLE_ASSIGNMENTS, seed=11) == pick_callout(reordered, seed=11)


@pytest.mark.parametrize("assignments", [{}, {1: {"cook": []}}])
def test_pick_callout_rejects_empty_schedule(assignments):
    with pytest.raises(ValueError):
        pick_callout(assignments, seed=0)


# Call-out simulation

def _callout_case():
    scenario = generate_restaurant_scenario(25)
    shift = scenario.shifts[0]
    employee = next(e for e in scenario.employees if _available(e, shift))
    return scenario, shift, employee


def test_apply_callout_makes_employee_unavailable_for_shift():
    scenario, shift, employee = _callout_case()

    updated = apply_callout(scenario.employees, employee.id, shift)
    called_out = next(e for e in updated if e.id == employee.id)

    assert not _available(called_out, shift)


def test_apply_callout_keeps_other_availability():
    scenario, shift, employee = _callout_case()

    updated = apply_callout(scenario.employees, employee.id, shift)
    called_out = next(e for e in updated if e.id == employee.id)

    for other in scenario.shifts:
        if other.starts_at >= shift.ends_at or other.ends_at <= shift.starts_at:
            assert _available(called_out, other) == _available(employee, other)


def test_apply_callout_leaves_other_employees_unchanged():
    scenario, shift, employee = _callout_case()

    updated = apply_callout(scenario.employees, employee.id, shift)

    for before, after in zip(scenario.employees, updated):
        if before.id != employee.id:
            assert before == after


def test_apply_callout_intervals_stay_valid():
    scenario, shift, employee = _callout_case()

    called_out = next(
        e for e in apply_callout(scenario.employees, employee.id, shift)
        if e.id == employee.id
    )

    for start, end in called_out.datetime_availability:
        assert end > start
        assert end <= shift.starts_at or start >= shift.ends_at


def test_apply_callout_rejects_unknown_employee():
    scenario = generate_restaurant_scenario(25)

    with pytest.raises(ValueError):
        apply_callout(scenario.employees, 999_999, scenario.shifts[0])
