from optimizer.sample_data import employees, shifts
from optimizer.solver import generate_schedule


def main():
    result = generate_schedule(employees, shifts)

    if result.assignments is None:
        print(f"Scheduling failed: {result.status}")
        return

    print(f"Scheduling status: {result.status}")

    # Display the generated schedule.
    for shift in shifts:
        print(
            f"\nDay {shift.day}, "
            f"{shift.start_hour}:00–{shift.end_hour}:00 "
            f"({shift.required_skill})"
        )

        for employee in employees:
            if employee.id in result.assignments[shift.id]:
                print(f"  - {employee.name}")

    # Display employee working hours.
    print("\nEmployee workload summary:")

    assigned_hours = []

    for employee in employees:
        total_hours = sum(
            shift.end_hour - shift.start_hour
            for shift in shifts
            if employee.id in result.assignments[shift.id]
        )

        assigned_hours.append(total_hours)

        print(
            f"{employee.name}: "
            f"{total_hours}/{employee.max_hours} hours"
        )

    # Calculate the fairness gap.
    fairness_gap = max(assigned_hours) - min(assigned_hours)

    print(f"\nFairness gap: {fairness_gap} hours")


if __name__ == "__main__":
    main()