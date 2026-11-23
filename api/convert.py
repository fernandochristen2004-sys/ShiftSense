"""Translate between API models and the scheduling engine's dataclasses."""

from datetime import datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api.schemas import (
    AssignmentRef,
    CalloutIn,
    ChangeOut,
    EmployeeIn,
    GenerateRequest,
    PolicyIn,
    RepairRequest,
    RepairResponse,
    ScheduleResponse,
    ShiftIn,
    ShortageOut,
)
from optimizer.models import (
    AvailabilityException,
    DateTimeShift,
    Employee,
    ScheduleResult,
    SchedulingPolicy,
    ShiftRequirement,
    WeeklyAvailability,
)


def to_timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown timezone: {name!r}.") from None


def to_employee(employee: EmployeeIn) -> Employee:
    datetime_availability = None
    if employee.datetime_availability is not None:
        datetime_availability = tuple(
            (interval.starts_at, interval.ends_at)
            for interval in employee.datetime_availability
        )

    return Employee(
        id=employee.id,
        name=employee.name,
        skills=frozenset(employee.skills),
        max_hours=employee.max_hours,
        target_minutes=employee.target_minutes,
        datetime_availability=datetime_availability,
        weekly_availability=tuple(
            WeeklyAvailability(rule.weekday, rule.start_time, rule.end_time)
            for rule in employee.weekly_availability
        ),
        availability_exceptions=tuple(
            AvailabilityException(
                date=exception.date,
                available=exception.available,
                intervals=tuple(
                    (interval.start_time, interval.end_time)
                    for interval in exception.intervals
                ),
            )
            for exception in employee.availability_exceptions
        ),
    )


def to_shift(shift: ShiftIn) -> DateTimeShift:
    return DateTimeShift(
        id=shift.id,
        starts_at=shift.starts_at,
        ends_at=shift.ends_at,
        requirements=tuple(
            ShiftRequirement(r.skill, r.count, r.min_count)
            for r in shift.requirements
        ),
    )


def to_policy(policy: PolicyIn) -> SchedulingPolicy:
    return SchedulingPolicy(**policy.model_dump())


def to_locks(locks: list[AssignmentRef]) -> dict[int, dict[str, list[int]]] | None:
    if not locks:
        return None
    result: dict[int, dict[str, list[int]]] = {}
    for lock in locks:
        result.setdefault(lock.shift_id, {}).setdefault(lock.role, []).append(lock.employee_id)
    return result


def to_engine_inputs(request: GenerateRequest) -> dict:
    """Build keyword arguments for `engine.generate()`.

    Raises ValueError (from the engine's own validation) for invalid data.
    """
    excluded: dict[int, list[int]] = {}
    for exclusion in request.excluded_assignments:
        excluded.setdefault(exclusion.shift_id, []).append(exclusion.employee_id)

    return {
        "employees": [to_employee(e) for e in request.employees],
        "shifts": [to_shift(s) for s in request.shifts],
        "policy": to_policy(request.policy),
        "scheduling_timezone": to_timezone(request.timezone),
        "locked_assignments": to_locks(request.locked_assignments),
        "excluded_assignments": excluded or None,
        "deterministic": request.deterministic,
    }


def to_schedule_response(result: ScheduleResult) -> ScheduleResponse:
    assignments = None
    if result.assignments is not None:
        assignments = [
            AssignmentRef(shift_id=shift_id, role=role, employee_id=employee_id)
            for shift_id, roles in sorted(result.assignments.items())
            for role, employee_ids in roles.items()
            for employee_id in sorted(employee_ids)
        ]

    return ScheduleResponse(
        status=result.status,
        assignments=assignments,
        fully_covered=result.fully_covered,
        shortages=[
            ShortageOut(shift_id=s.shift_id, role=s.role, missing=s.missing)
            for s in result.shortages
        ],
        conflicts=list(result.conflicts),
        validation_errors=list(result.validation_errors),
        objective_values=dict(result.objective_values or {}),
        stage_statuses=dict(result.stage_statuses or {}),
        schedule_metrics=dict(result.schedule_metrics or {}),
        assignment_changes=result.assignment_changes,
    )


# Repair

def to_original_schedule(
    assignments: list[AssignmentRef],
    shifts: list[DateTimeShift],
) -> dict[int, dict[str, list[int]]]:
    """Build the engine's schedule format: every shift and role, even if empty."""
    schedule = {
        shift.id: {requirement.skill: [] for requirement in shift.requirements}
        for shift in shifts
    }
    for assignment in assignments:
        roles = schedule.get(assignment.shift_id)
        if roles is None:
            raise ValueError(
                f"Original schedule refers to unknown shift {assignment.shift_id}."
            )
        if assignment.role not in roles:
            raise ValueError(
                f"Shift {assignment.shift_id} has no {assignment.role!r} role."
            )
        roles[assignment.role].append(assignment.employee_id)
    return schedule


def callout_window(
    shift: DateTimeShift,
    scheduling_timezone: tzinfo,
    rest_of_day: bool,
) -> tuple[datetime, datetime]:
    """The period a call-out keeps the employee off work.

    By default: from the shift's start until 06:00 the next morning in the
    restaurant's timezone (or the shift's end, if later).
    """
    if not rest_of_day:
        return shift.starts_at, shift.ends_at

    local_start = shift.starts_at.astimezone(scheduling_timezone)
    next_morning = datetime.combine(
        local_start.date() + timedelta(days=1),
        time(6, 0),
        tzinfo=scheduling_timezone,
    )
    return shift.starts_at, max(shift.ends_at, next_morning)


def callout_exclusions(
    callouts: list[CalloutIn],
    shifts: list[DateTimeShift],
    original: dict[int, dict[str, list[int]]],
    scheduling_timezone: tzinfo,
) -> dict[int, list[int]]:
    """Turn call-outs into 'must not work' exclusions for the engine."""
    shifts_by_id = {shift.id: shift for shift in shifts}
    excluded: dict[int, list[int]] = {}

    for callout in callouts:
        shift = shifts_by_id.get(callout.shift_id)
        if shift is None:
            raise ValueError(f"Call-out refers to unknown shift {callout.shift_id}.")

        scheduled = any(
            callout.employee_id in employee_ids
            for employee_ids in original[callout.shift_id].values()
        )
        if not scheduled:
            raise ValueError(
                f"Employee {callout.employee_id} is not scheduled on shift "
                f"{callout.shift_id}, so they can't call out of it."
            )

        start, end = callout_window(shift, scheduling_timezone, callout.rest_of_day)
        for other in shifts:
            if other.starts_at < end and start < other.ends_at:
                ids = excluded.setdefault(other.id, [])
                if callout.employee_id not in ids:
                    ids.append(callout.employee_id)

    return excluded


def to_repair_inputs(request: RepairRequest) -> dict:
    """Build keyword arguments for `engine.repair()`."""
    inputs = to_engine_inputs(request)
    original = to_original_schedule(request.original_assignments, inputs["shifts"])

    excluded = dict(inputs["excluded_assignments"] or {})
    for shift_id, employee_ids in callout_exclusions(
        request.callouts,
        inputs["shifts"],
        original,
        inputs["scheduling_timezone"],
    ).items():
        merged = excluded.setdefault(shift_id, [])
        merged.extend(e for e in employee_ids if e not in merged)

    inputs["excluded_assignments"] = excluded or None
    inputs["original_schedule"] = original
    return inputs


def schedule_changes(
    before: dict[int, dict[str, list[int]]],
    after: dict[int, dict[str, list[int]]],
) -> list[ChangeOut]:
    """List each employee whose role on a shift changed (including on/off)."""
    changes = []
    for shift_id in sorted(before.keys() | after.keys()):
        old = {e: r for r, ids in before.get(shift_id, {}).items() for e in ids}
        new = {e: r for r, ids in after.get(shift_id, {}).items() for e in ids}
        for employee_id in sorted(old.keys() | new.keys()):
            if old.get(employee_id) != new.get(employee_id):
                changes.append(ChangeOut(
                    shift_id=shift_id,
                    employee_id=employee_id,
                    before_role=old.get(employee_id),
                    after_role=new.get(employee_id),
                ))
    return changes


def to_repair_response(
    result: ScheduleResult,
    original: dict[int, dict[str, list[int]]],
) -> RepairResponse:
    base = to_schedule_response(result)
    changes = None
    if result.assignments is not None:
        changes = schedule_changes(original, result.assignments)
    return RepairResponse(**base.model_dump(), changes=changes)
