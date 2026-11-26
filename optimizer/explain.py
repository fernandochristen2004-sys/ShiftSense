"""Explain why a gap left by call-outs can't be filled.

When a repair fails, the solver only says "infeasible". This module looks at
each slot the call-outs emptied and, for everyone who has the right skill,
finds the first rule that keeps them out of it. Reasons are structured (a
short code plus details) so a dashboard can lay them out; `summarize` turns
them into one sentence for logs and plain-text clients:

    Omar is off Sat 28 17:00-23:00 (bartender). Other bartenders:
    Jade (on this shift as server), Ravi (not available),
    Tharindu (needs rest around Sat 28 23:00-02:00).

Reasons are judged against the current schedule, one person at a time. The
solver can also move people around, so someone with no blocking reason is
reported as free. If every gap has someone free, the problem is the
combination (they can't all be used at once), and `together_only` says so.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import tzinfo
from typing import Literal

from optimizer.models import DateTimeShift, Employee, FixedAssignment, SchedulingPolicy
from optimizer.timeutils import (
    datetime_shifts_overlap,
    datetime_shifts_violate_rest_policy,
    employee_is_available,
    shift_duration_minutes,
)

Schedule = Mapping[int, Mapping[str, Iterable[int]]]  # shift_id -> role -> employee ids

# In the order a manager can most easily act on them.
Reason = Literal["on_shift", "busy", "rest", "max_hours", "unavailable", "called_out"]
REASON_ORDER: tuple[Reason, ...] = (
    "on_shift", "busy", "rest", "max_hours", "unavailable", "called_out",
)


@dataclass(frozen=True)
class Candidate:
    """Someone with the right skill, and what keeps them out of the slot."""

    employee_id: int
    name: str
    reason: Reason | None  # None: nothing obvious stops them
    other_shift_id: int | None = None  # busy / rest: the shift in the way
    other_role: str | None = None      # on_shift: the role they already have
    worked_minutes: int | None = None  # max_hours: minutes already scheduled
    max_hours: int | None = None       # max_hours: their limit


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


@dataclass(frozen=True)
class Explanation:
    gaps: tuple[Gap, ...]
    together_only: bool  # every gap has someone free, just not all at once

    @property
    def blocking(self) -> tuple[Gap, ...]:
        """The gaps nobody can fill; all gaps when it's the combination."""
        return tuple(gap for gap in self.gaps if not gap.anyone_free) or self.gaps


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
) -> Explanation:
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
                _candidate(
                    employee, shift, working.get(employee.id, []), excluded,
                    policy, scheduling_timezone,
                )
                for employee in sorted(employees_by_id.values(), key=lambda e: e.name)
                if role in employee.skills and employee.id not in removed
            )
            gaps.append(Gap(shift_id, role, removed, candidates))

    gaps = tuple(gaps)
    return Explanation(gaps, together_only=bool(gaps) and all(g.anyone_free for g in gaps))


def _candidate(
    employee: Employee,
    shift: DateTimeShift,
    working: list[tuple[DateTimeShift, str]],
    excluded: Mapping[int, set[int]],
    policy: SchedulingPolicy,
    scheduling_timezone: tzinfo,
) -> Candidate:
    """This person, with the first rule that keeps them out of the shift."""
    def blocked(reason: Reason, **details) -> Candidate:
        return Candidate(employee.id, employee.name, reason, **details)

    if employee.id in excluded.get(shift.id, set()):
        return blocked("called_out")
    for other, role in working:
        if other.id == shift.id:
            return blocked("on_shift", other_role=role)
    if not employee_is_available(employee, shift, scheduling_timezone):
        return blocked("unavailable")
    for other, _ in working:
        if datetime_shifts_overlap(shift, other):
            return blocked("busy", other_shift_id=other.id)
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
                return blocked("rest", other_shift_id=other.id)
    worked = sum(shift_duration_minutes(other) for other, _ in working)
    if worked + shift_duration_minutes(shift) > employee.max_hours * 60:
        return blocked("max_hours", worked_minutes=worked, max_hours=employee.max_hours)
    return Candidate(employee.id, employee.name, None)


def reason_text(
    candidate: Candidate,
    shifts_by_id: Mapping[int, DateTimeShift],
    scheduling_timezone: tzinfo,
) -> str:
    """A few words: 'not available', 'needs rest around Sat 28 23:00-02:00'."""
    def other() -> str:
        shift = shifts_by_id.get(candidate.other_shift_id)
        return shift_label(shift, scheduling_timezone) if shift else "another shift"

    match candidate.reason:
        case None:
            return "free"
        case "called_out":
            return "called out"
        case "on_shift":
            return f"on this shift as {candidate.other_role}"
        case "unavailable":
            return "not available"
        case "busy":
            return f"working {other()}"
        case "rest":
            return f"needs rest around {other()}"
        case "max_hours":
            return f"at max hours ({candidate.worked_minutes / 60:g} of {candidate.max_hours} h)"


def summarize(
    explanation: Explanation,
    shifts: Iterable[DateTimeShift],
    scheduling_timezone: tzinfo,
    names: Mapping[int, str],
) -> str:
    """One sentence per blocking gap, for logs and plain-text clients."""
    shifts_by_id = {shift.id: shift for shift in shifts}
    parts = []
    for gap in explanation.blocking:
        who = ", ".join(names.get(e, f"#{e}") for e in gap.called_out)
        where = shift_label(shifts_by_id[gap.shift_id], scheduling_timezone)
        others = sorted(
            (c for c in gap.candidates if c.reason != "called_out"),
            key=lambda c: (REASON_ORDER.index(c.reason) if c.reason else -1, c.name),
        )
        if not others:
            parts.append(f"{who} is off {where} ({gap.role}), and nobody else works {gap.role}.")
            continue
        listed = ", ".join(
            f"{c.name} ({reason_text(c, shifts_by_id, scheduling_timezone)})" for c in others
        )
        parts.append(f"{who} is off {where} ({gap.role}). Other {gap.role}s: {listed}.")
    if explanation.together_only:
        parts.append("Each gap has someone free on its own, but not all at once.")
    return " ".join(parts)
