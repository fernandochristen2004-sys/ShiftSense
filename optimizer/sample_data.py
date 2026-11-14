from optimizer.models import Employee, Shift


employees = [
    Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server", "cashier"}),
        max_hours=20,
    ),
    Employee(
        id=2,
        name="Bob",
        skills=frozenset({"server"}),
        max_hours=16,
    ),
    Employee(
        id=3,
        name="Charlie",
        skills=frozenset({"cashier"}),
        max_hours=16,
    ),
    Employee(
        id=4,
        name="Diana",
        skills=frozenset({"server", "cashier"}),
        max_hours=20,
    ),
    Employee(
        id=5,
        name="Ethan",
        skills=frozenset({"server"}),
        max_hours=12,
    ),
]

shifts = [
    Shift(
        id=1,
        day=0,
        start_hour=9,
        end_hour=13,
        required_staff=2,
        required_skill="server",
    ),
    Shift(
        id=2,
        day=0,
        start_hour=13,
        end_hour=17,
        required_staff=1,
        required_skill="cashier",
    ),
    Shift(
        id=3,
        day=1,
        start_hour=9,
        end_hour=13,
        required_staff=2,
        required_skill="server",
    ),
    Shift(
        id=4,
        day=1,
        start_hour=13,
        end_hour=17,
        required_staff=1,
        required_skill="cashier",
    ),
    Shift(
        id=5,
        day=2,
        start_hour=9,
        end_hour=13,
        required_staff=2,
        required_skill="server",
    ),
    Shift(
        id=6,
        day=2,
        start_hour=13,
        end_hour=17,
        required_staff=1,
        required_skill="cashier",
    ),
]

if __name__ == "__main__":
    print(f"Employees: {len(employees)}")
    print(f"Shifts: {len(shifts)}")

    for shift in shifts:
        print(
            f"Shift {shift.id}: "
            f"Day {shift.day}, "
            f"{shift.start_hour}:00–{shift.end_hour}:00, "
            f"{shift.required_staff} {shift.required_skill}(s)"
        )