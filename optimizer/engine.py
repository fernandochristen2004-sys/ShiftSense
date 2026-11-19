
"""Public entry points for ShiftSense scheduling."""

from dataclasses import replace
from datetime import timezone, tzinfo

from optimizer.models import (
    DateTimeShift,
    Employee,
    FixedAssignment,
    ScheduleResult,
    SchedulingPolicy,
)
from optimizer.solver import generate_schedule
from optimizer.validator import validate_schedule


def _run(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    policy: SchedulingPolicy,
    original_schedule: dict[int, dict[str, list[int]]] | None = None,
    outside_assignments: tuple[FixedAssignment, ...] = (),
    locked_assignments: dict[int, dict[str, list[int]]] | None = None,
    excluded_assignments: dict[int, list[int]] | None = None,
    scheduling_timezone: tzinfo = timezone.utc,
) -> ScheduleResult:
    """Run the existing solver and independently validate its output."""

    result = generate_schedule(
        employees=employees,
        shifts=shifts,
        original_schedule=original_schedule,
        policy=policy,
        scheduling_timezone=scheduling_timezone,
        outside_assignments=outside_assignments,
        locked_assignments=locked_assignments,
        excluded_assignments=excluded_assignments,
    )

    # No schedule exists to validate for INFEASIBLE/UNKNOWN results.
    if result.assignments is None:
        return result

    errors = validate_schedule(
        employees=employees,
        shifts=shifts,
        schedule=result.assignments,
        policy=policy,
        scheduling_timezone=scheduling_timezone,
        outside_assignments=outside_assignments,
        locked_assignments=locked_assignments,
        excluded_assignments=excluded_assignments,
    )

    # Preserve solver metadata and expose independent rule violations.
    return replace(
        result,
        validation_errors=tuple(errors),
    )


def generate(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    policy: SchedulingPolicy,
    outside_assignments: tuple[FixedAssignment, ...] = (),
    locked_assignments: dict[int, dict[str, list[int]]] | None = None,
    excluded_assignments: dict[int, list[int]] | None = None,
    scheduling_timezone: tzinfo = timezone.utc,
) -> ScheduleResult:
    """Generate and validate a new restaurant schedule."""

    return _run(
        employees=employees,
        shifts=shifts,
        policy=policy,
        outside_assignments=outside_assignments,
        locked_assignments=locked_assignments,
        excluded_assignments=excluded_assignments,
        scheduling_timezone=scheduling_timezone,
    )


def repair(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    policy: SchedulingPolicy,
    original_schedule: dict[int, dict[str, list[int]]],
    outside_assignments: tuple[FixedAssignment, ...] = (),
    locked_assignments: dict[int, dict[str, list[int]]] | None = None,
    excluded_assignments: dict[int, list[int]] | None = None,
    scheduling_timezone: tzinfo = timezone.utc,
) -> ScheduleResult:
    """Repair and independently validate an existing schedule."""

    return _run(
        employees=employees,
        shifts=shifts,
        policy=policy,
        original_schedule=original_schedule,
        outside_assignments=outside_assignments,
        locked_assignments=locked_assignments,
        excluded_assignments=excluded_assignments,
        scheduling_timezone=scheduling_timezone,
    )
