from optimizer.models import Employee, DateTimeShift
from datetime import datetime, timezone

def sample_datetime(day: int, hour: int) -> datetime:
    """Return a UTC datetime for a sample scheduling day."""
    return datetime(
        2026, 11, 23 + day, hour, 0,
        tzinfo=timezone.utc,
    )

employees = [
    Employee(
        id=1,
        name="Alice",
        skills=frozenset({"server", "cashier"}),
        max_hours=20,
        datetime_availability=(
            (sample_datetime(0, 9), sample_datetime(0, 13)),
            (sample_datetime(1, 13), sample_datetime(1, 17)),
            (sample_datetime(2, 9), sample_datetime(2, 17)),
        ),
    ),
    Employee(
        id=2,
        name="Bob",
        skills=frozenset({"server"}),
        max_hours=16,
        datetime_availability=(
            (sample_datetime(0, 9), sample_datetime(0, 13)),
            (sample_datetime(1, 9), sample_datetime(1, 13)),
        ),
    ),
    Employee(
        id=3,
        name="Charlie",
        skills=frozenset({"cashier"}),
        max_hours=16,
        datetime_availability=(
            (sample_datetime(0, 0), sample_datetime(1, 0)),
            (sample_datetime(1, 0), sample_datetime(2, 0)),
            (sample_datetime(2, 0), sample_datetime(3, 0)),
        ),
    ),
    Employee(
        id=4,
        name="Diana",
        skills=frozenset({"server", "cashier"}),
        max_hours=20,
        datetime_availability=(
            (sample_datetime(0, 0), sample_datetime(1, 0)),
            (sample_datetime(1, 0), sample_datetime(2, 0)),
            (sample_datetime(2, 0), sample_datetime(3, 0)),
        ),
    ),
    Employee(
        id=5,
        name="Ethan",
        skills=frozenset({"server"}),
        max_hours=12,
        datetime_availability=(
            (sample_datetime(0, 0), sample_datetime(1, 0)),
            (sample_datetime(1, 0), sample_datetime(2, 0)),
            (sample_datetime(2, 0), sample_datetime(3, 0)),
        ),
    ),
]

shifts = [
    DateTimeShift(
        id=1,
        starts_at=sample_datetime(0, 9),
        ends_at=sample_datetime(0, 13),
        required_staff=2,
        required_skill="server",
    ),
    DateTimeShift(
        id=2,
        starts_at=sample_datetime(0, 13),
        ends_at=sample_datetime(0, 17),
        required_staff=1,
        required_skill="cashier",
    ),
    DateTimeShift(
        id=3,
        starts_at=sample_datetime(1, 9),
        ends_at=sample_datetime(1, 13),
        required_staff=2,
        required_skill="server",
    ),
    DateTimeShift(
        id=4,
        starts_at=sample_datetime(1, 13),
        ends_at=sample_datetime(1, 17),
        required_staff=1,
        required_skill="cashier",
    ),
    DateTimeShift(
        id=5,
        starts_at=sample_datetime(2, 9),
        ends_at=sample_datetime(2, 13),
        required_staff=2,
        required_skill="server",
    ),
    DateTimeShift(
        id=6,
        starts_at=sample_datetime(2, 13),
        ends_at=sample_datetime(2, 17),
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
            f"{shift.starts_at:%a %d %b %H:%M} – "
            f"{shift.ends_at:%a %d %b %H:%M} UTC, "
            f"{shift.required_staff} {shift.required_skill}(s)"
        )
