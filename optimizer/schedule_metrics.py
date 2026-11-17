from optimizer.models import DateTimeShift, Employee
from optimizer.timeutils import shift_duration_minutes


def calculate_schedule_metrics(
    employees: list[Employee],
    shifts: list[DateTimeShift],
    schedule: dict[int, dict[str, list[int]]],
) -> dict[str, int]:
    """Measure workload fairness in a completed schedule."""

    assigned_minutes = {
        employee.id: 0
        for employee in employees
    }

    for shift in shifts:
        duration = shift_duration_minutes(shift)

        for employee_ids in schedule[shift.id].values():
            for employee_id in employee_ids:
                assigned_minutes[employee_id] += duration

    target_deviations = [
        abs(
            assigned_minutes[employee.id]
            - employee.target_minutes
        )
        for employee in employees
        if employee.target_minutes is not None
    ]

    untargeted_minutes = [
        assigned_minutes[employee.id]
        for employee in employees
        if employee.target_minutes is None
    ]

    metrics = {}

    if target_deviations:
        metrics["target_deviation_min"] = sum(
            target_deviations
        )

        metrics["max_deviation_min"] = max(
            target_deviations
        )

    if len(untargeted_minutes) >= 2:
        metrics["untargeted_gap_min"] = (
            max(untargeted_minutes)
            - min(untargeted_minutes)
        )

    return metrics
