from dataclasses import dataclass


@dataclass(frozen=True)
class Employee:
    id: int
    name: str
    skills: frozenset[str]
    max_hours: int
    available_days: frozenset[int] = frozenset(range(7))
    availability: tuple["Availability", ...] | None = None

    def __post_init__(self):
        if self.id <= 0:
            raise ValueError("Employee ID must be positive.")

        if not self.name.strip():
            raise ValueError("Employee name cannot be empty.")

        if self.max_hours < 0:
            raise ValueError(
                "Maximum working hours cannot be negative."
            )

        if not all(0 <= day <= 6 for day in self.available_days):
            raise ValueError(
                "Available days must be between 0 and 6."
            )

@dataclass(frozen=True)
class Shift:
    id: int
    day: int
    start_hour: int
    end_hour: int
    required_staff: int
    required_skill: str

    def __post_init__(self):
        if self.id <= 0:
            raise ValueError("Shift ID must be positive.")

        if not 0 <= self.day <= 6:
            raise ValueError("Shift day must be between 0 and 6.")

        if not 0 <= self.start_hour < 24:
            raise ValueError("Invalid shift start hour.")

        if not 0 < self.end_hour <= 24:
            raise ValueError("Invalid shift end hour.")

        if self.start_hour >= self.end_hour:
            raise ValueError(
                "Shift end hour must be after start hour."
            )

        if self.required_staff < 0:
            raise ValueError(
                "Required staff cannot be negative."
            )

        if not self.required_skill.strip():
            raise ValueError(
                "Required skill cannot be empty."
            )

@dataclass(frozen=True)
class Availability:
    day: int
    start_hour: int
    end_hour: int

    def __post_init__(self):
        if not 0 <= self.day <= 6:
            raise ValueError(
                "Availability day must be between 0 and 6."
            )

        if not 0 <= self.start_hour < 24:
            raise ValueError(
                "Invalid availability start hour."
            )

        if not 0 < self.end_hour <= 24:
            raise ValueError(
                "Invalid availability end hour."
            )

        if self.start_hour >= self.end_hour:
            raise ValueError(
                "Availability end hour must be after start hour."
            )

@dataclass(frozen=True)
class ScheduleResult:
    status: str
    assignments: dict[int, list[int]] | None

@dataclass(frozen=True)
class SchedulingPolicy:
    minimum_rest_hours: int = 0
    enforce_minimum_rest: bool = False
    fairness_enabled: bool = True

    def __post_init__(self):
        if type(self.minimum_rest_hours) is not int:
            raise ValueError(
                "Minimum rest hours must be an integer."
            )

        if self.minimum_rest_hours < 0:
            raise ValueError(
                "Minimum rest hours cannot be negative."
            )

        if not isinstance(self.enforce_minimum_rest, bool):
            raise ValueError(
                "Enforce minimum rest must be a Boolean."
            )

        if not isinstance(self.fairness_enabled, bool):
            raise ValueError(
                "Fairness enabled must be a Boolean."
            )