"""Explain why a gap left by call-outs can't be filled.

When a repair fails, the solver only says "infeasible". This module looks at
each slot the call-outs emptied and, for everyone who has the right skill,
gives the first rule that keeps them out of it:

    Omar is off Sat 28 17:00-23:00 (bartender).
    Who else could work bartender: Jade (not available), Tharindu (working
    Sat 28 23:00-02:00, too little rest).

The reasons are judged against the current schedule, one person at a time.
The solver can also move people around, so a person with no blocking reason
is reported as "free". If every gap has someone free, the problem is the
combination (they can't all be used at once), and the explanation says so.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import tzinfo

from optimizer.models import DateTimeShift, Employee, FixedAssignment, SchedulingPolicy
from optimizer.timeutils import (
    datetime_shifts_overlap,
    datetime_shifts_violate_rest_policy,
    employee_is_available,
    shift_duration_minutes,
)

Schedule = Mapping[int, Mapping[str, Iterable[int]]]  # shift_id -> role -> employee ids


@dataclass(frozen=True)
class Candidate:
    """Someone with the right skill, and why they can't take the slot."""

    employee_id: int
    name: str
    reason: str | None  # None: nothing obvious stops them


@dataclass(frozen=True)
class Gap:
    """A slot emptied by a call-out."""

    shift_id: int
    role: str
    called_out: tuple[int, ...]  # employee ids removed from this slot
    candidates: tuple[Candidate, ...]

    @property
    def anyone_free(self) -> bool:
        return any(candidate.reason is None for candidate in self.candidates)


def shift_label(shift: DateTimeShift, scheduling_timezone: tzinfo) -> str:
    """'Sat 28 17:00-23:00' in restaurant time."""
    start = shift.starts_at.astimezone(scheduling_timezone)
    end = shift.ends_at.astimezone(scheduling_timezone)
    return f"{start:%a} {start.day} {start:%H:%M}-{end:%H:%M}"


def explain_gaps(
    employees: Iterable[Employee],
    shifts: Iterable[DateTimeShift],
    policy: SchedulingPolicy,
    original_schedule: Schedule,
    excluded_assignments: Mapping[int, Iterable[int]],
    scheduling_timezone: tzinfo,
    outside_assignments: Iterable[FixedAssignment] = (),
) -> list[Gap]:
    """Explain each slot the excluded people leave empty, in shift order."""
    employees_by_id = {employee.id: employee for employee in employees}
    shifts_by_id = {shift.id: shift for shift in shifts}
    excluded = {shift_id: set(ids) for shift_id, ids in excluded_assignments.items()}

    # What everyone is working, once the excluded people are taken off.
    working: dict[int, list[tuple[DateTimeShift, str]]] = {}
    for shift_id, roles in original_schedule.items():
        for role, employee_ids in roles.items():
            for employee_id in employee_ids:
                if employee_id not in excluded.get(shift_id, set()):
                    working.setdefault(employee_id, []).append((shifts_by_id[shift_id], role))
    for fixed in outside_assignments:
        working.setdefault(fixed.employee_id, []).append((fixed.shift, ""))

    gaps = []
    for shift_id in sorted(excluded, key=lambda sid: shifts_by_id[sid].starts_at):
        shift = shifts_by_id[shift_id]
        for role, employee_ids in original_schedule.get(shift_id, {}).items():
            removed = tuple(sorted(set(employee_ids) & excluded[shift_id]))
            if not removed:
                continue
            candidates = tuple(
                Candidate(
                    employee.id,
                    employee.name,
                    _reason(
                        employee, shift, working.get(employee.id, []), excluded,
                        policy, scheduling_timezone,
                    ),
                )
                for employee in sorted(employees_by_id.values(), key=lambda e: e.name)
                if role in employee.skills and employee.id not in removed
            )
            gaps.append(Gap(shift_id, role, removed, candidates))
    return gaps


def _reason(
    employee: Employee,
    shift: DateTimeShift,
    working: list[tuple[DateTimeShift, str]],
    excluded: Mapping[int, set[int]],
    policy: SchedulingPolicy,
    scheduling_timezone: tzinfo,
) -> str | None:
    """The first rule that keeps this person out of the shift, or None."""
    if employee.id in excluded.get(shift.id, set()):
        return "called out"
    for other, role in working:
        if other.id == shift.id:
            return f"already on this shift as {role}"
    if not employee_is_available(employee, shift, scheduling_timezone):
        return "not available"
    for other, _ in working:
        if datetime_shifts_overlap(shift, other):
            return f"working {shift_label(other, scheduling_timezone)}"
    if policy.enforce_minimum_rest:
        for other, _ in working:
            if datetime_shifts_violate_rest_policy(
                shift,
                other,
                policy.minimum_rest_hours * 60,
                allow_split_shifts=policy.allow_split_shifts,
                split_shift_min_break_minutes=policy.split_shift_min_break_minutes,
                max_split_span_minutes=policy.max_split_span_minutes,
            ):
                return f"too little rest around {shift_label(other, scheduling_timezone)}"
    worked = sum(shift_duration_minutes(other) for other, _ in working)
    if worked + shift_duration_minutes(shift) > employee.max_hours * 60:
        return f"would go over {employee.max_hours} h (already {worked / 60:g} h)"
    return None


def summarize(gaps: list[Gap], scheduling_timezone: tzinfo, shifts: Iterable[DateTimeShift],
              names: Mapping[int, str]) -> str:
    """One readable paragraph for a manager."""
    shifts_by_id = {shift.id: shift for shift in shifts}
    blocking = [gap for gap in gaps if not gap.anyone_free] or gaps
    parts = []
    for gap in blocking:
        who = ", ".join(names.get(e, f"#{e}") for e in gap.called_out)
        where = shift_label(shifts_by_id[gap.shift_id], scheduling_timezone)
        others = [c for c in gap.candidates if c.reason != "called out"]
        if not others:
            parts.append(f"{who} is off {where} ({gap.role}), and nobody else works {gap.role}.")
            continue
        listed = ", ".join(
            f"{c.name} ({c.reason or 'free'})" for c in others
        )
        parts.append(
            f"{who} is off {where} ({gap.role}). Who else works {gap.role}: {listed}."
        )
    if all(gap.anyone_free for gap in gaps):
        parts.append(
            "Each gap has someone free on its own, but not all at once without breaking a rule."
        )
    return " ".join(parts)
