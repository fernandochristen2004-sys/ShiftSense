from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Employee:
    id: int
    name: str
    skills: frozenset[str]
    max_hours: int
    datetime_availability: tuple[
        tuple[datetime, datetime], ...
    ] | None = None

    def __post_init__(self):
        if self.id <= 0:
            raise ValueError("Employee ID must be positive.")

        if not self.name.strip():
            raise ValueError("Employee name cannot be empty.")

        if self.max_hours < 0:
            raise ValueError(
                "Maximum working hours cannot be negative."
            )

        if self.datetime_availability is not None:
            for start, end in self.datetime_availability:
                if not isinstance(start, datetime) or not isinstance(
                    end, datetime
                ):
                    raise ValueError(
                        "Availability boundaries must be datetimes."
                    )

                if (
                    start.utcoffset() is None
                    or end.utcoffset() is None
                ):
                    raise ValueError(
                        "Availability must be timezone-aware."
                    )

                if (
                    start.second != 0
                    or start.microsecond != 0
                    or end.second != 0
                    or end.microsecond != 0
                ):
                    raise ValueError(
                        "Availability must have minute precision."
                    )

                if end <= start:
                    raise ValueError(
                        "Availability end must be after start."
                    )


@dataclass(frozen=True)
class DateTimeShift:
    id: int
    starts_at: datetime
    ends_at: datetime
    required_staff: int
    required_skill: str

    def __post_init__(self):
        if self.id <= 0:
            raise ValueError("Shift ID must be positive.")

        if not isinstance(self.starts_at, datetime) or not isinstance(
            self.ends_at, datetime
        ):
            raise ValueError(
                "Shift boundaries must be datetimes."
            )

        if self.starts_at.utcoffset() is None:
            raise ValueError(
                "Shift start must be timezone-aware."
            )

        if self.ends_at.utcoffset() is None:
            raise ValueError(
                "Shift end must be timezone-aware."
            )

        if (
            self.starts_at.second != 0
            or self.starts_at.microsecond != 0
            or self.ends_at.second != 0
            or self.ends_at.microsecond != 0
        ):
            raise ValueError(
                "Shift times must have minute precision."
            )

        if self.ends_at <= self.starts_at:
            raise ValueError(
                "Shift end must be after shift start."
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