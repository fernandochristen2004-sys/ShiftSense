from dataclasses import dataclass


@dataclass(frozen=True)
class Employee:
    id: int
    name: str
    skills: frozenset[str]
    max_hours: int
    available_days: frozenset[int] = frozenset(range(7))
    availability: tuple["Availability", ...] | None = None

@dataclass(frozen=True)
class Shift:
    id: int
    day: int
    start_hour: int
    end_hour: int
    required_staff: int
    required_skill: str

@dataclass(frozen=True)
class Availability:
    day: int
    start_hour: int
    end_hour: int

@dataclass(frozen=True)
class ScheduleResult:
    status: str
    assignments: dict[int, list[int]] | None