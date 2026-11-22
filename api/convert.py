"""Translate between API models and the scheduling engine's dataclasses."""

from datetime import tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api.schemas import (
    AssignmentRef,
    EmployeeIn,
    GenerateRequest,
    PolicyIn,
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
