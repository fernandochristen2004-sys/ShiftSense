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
            f"\nShift {shift.id}: "
            f"{shift.starts_at:%a %d %b %H:%M} – "
            f"{shift.ends_at:%a %d %b %H:%M} UTC"
        )

        for requirement in shift.requirements:
            skill = requirement.skill
            print(f"  {skill}:")

            for employee in employees:
                if employee.id in result.assignments[shift.id][skill]:
                    print(f"    - {employee.name}")

    # Display employee working hours.
    print("\nEmployee workload summary:")

    assigned_hours = []

    for employee in employees:
        total_hours = sum(
            (shift.ends_at - shift.starts_at).total_seconds() / 3600
            for shift in shifts
            if any(
                employee.id in assigned_ids
                for assigned_ids in result.assignments[shift.id].values()
            )
        )

        assigned_hours.append(total_hours)

        print(
            f"{employee.name}: "
            f"{total_hours:g}/{employee.max_hours} hours"
        )

    # Calculate the fairness gap.
    fairness_gap = max(assigned_hours) - min(assigned_hours)

    print(f"\nFairness gap: {fairness_gap:g} hours")


if __name__ == "__main__":
    main()