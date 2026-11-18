from optimizer.models import (
    DateTimeShift,
    StaffingShortage,
)


def calculate_coverage(
    shifts: list[DateTimeShift],
    schedule: dict[int, dict[str, list[int]]],
) -> tuple[bool, tuple[StaffingShortage, ...]]:
    """Measure target staffing coverage in a returned schedule."""
    shortages = []

    for shift in shifts:
        assigned_roles = schedule.get(shift.id, {})

        for requirement in shift.requirements:
            assigned_count = len(
                assigned_roles.get(requirement.skill, [])
            )

            missing = requirement.count - assigned_count

            if missing > 0:
                shortages.append(
                    StaffingShortage(
                        shift_id=shift.id,
                        role=requirement.skill,
                        missing=missing,
                    )
                )

    return not shortages, tuple(shortages)
