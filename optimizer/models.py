from dataclasses import dataclass
from datetime import datetime, time, date

@dataclass(frozen=True)
class WeeklyAvailability:
    weekday: int
    start_time: time
    end_time: time

    def __post_init__(self):
        if type(self.weekday) is not int or not 0 <= self.weekday <= 6:
            raise ValueError(
                "Weekday must be an integer between 0 and 6."
            )

        if (
            not isinstance(self.start_time, time)
            or not isinstance(self.end_time, time)
        ):
            raise ValueError(
                "Weekly availability boundaries must be times."
            )

        if (
            self.start_time.tzinfo is not None
            or self.end_time.tzinfo is not None
        ):
            raise ValueError(
                "Weekly availability times must be timezone-naive."
            )

        if (
            self.start_time.second != 0
            or self.start_time.microsecond != 0
            or self.end_time.second != 0
            or self.end_time.microsecond != 0
        ):
            raise ValueError(
                "Weekly availability must have minute precision."
            )

        if self.end_time == self.start_time:
            raise ValueError(
                "Weekly availability start and end cannot be equal."
            )

@dataclass(frozen=True)
class AvailabilityException:
    date: date
    available: bool
    intervals: tuple[tuple[time, time], ...] = ()

    def __post_init__(self):
        if type(self.date) is not date:
            raise ValueError(
                "Availability exception date must be a date."
            )

        if type(self.available) is not bool:
            raise ValueError(
                "Availability exception available must be a Boolean."
            )

        if not isinstance(self.intervals, tuple):
            raise ValueError(
                "Availability exception intervals must be a tuple."
            )

        if self.available and not self.intervals:
            raise ValueError(
                "Available exceptions must specify time intervals."
            )

        if not self.available and self.intervals:
            raise ValueError(
                "Unavailable exceptions cannot specify time intervals."
            )

        for interval in self.intervals:
            if (
                not isinstance(interval, tuple)
                or len(interval) != 2
            ):
                raise ValueError(
                    "Each exception interval must contain two times."
                )

            start, end = interval

            if (
                not isinstance(start, time)
                or not isinstance(end, time)
            ):
                raise ValueError(
                    "Exception interval boundaries must be times."
                )

            if start.tzinfo is not None or end.tzinfo is not None:
                raise ValueError(
                    "Exception interval times must be timezone-naive."
                )

            if (
                start.second != 0
                or start.microsecond != 0
                or end.second != 0
                or end.microsecond != 0
            ):
                raise ValueError(
                    "Exception intervals must have minute precision."
                )

            if end <= start:
                raise ValueError(
                    "Exception interval end must be after start."
                )

@dataclass(frozen=True)
class Employee:
    id: int
    name: str
    skills: frozenset[str]
    max_hours: int
    datetime_availability: tuple[
        tuple[datetime, datetime], ...
    ] | None = None
    weekly_availability: tuple[
        WeeklyAvailability, ...
    ] = ()
    availability_exceptions: tuple[
        AvailabilityException, ...
    ] = ()

    def __post_init__(self):
        if self.id <= 0:
            raise ValueError("Employee ID must be positive.")

        if not self.name.strip():
            raise ValueError("Employee name cannot be empty.")

        if self.max_hours < 0:
            raise ValueError(
                "Maximum working hours cannot be negative."
            )

        if not isinstance(self.weekly_availability, tuple):
            raise ValueError(
                "Weekly availability must be a tuple."
            )

        for rule in self.weekly_availability:
            if not isinstance(rule, WeeklyAvailability):
                raise ValueError(
                    "Weekly availability must contain "
                    "WeeklyAvailability objects."
                )

        if not isinstance(self.availability_exceptions, tuple):
            raise ValueError(
                "Availability exceptions must be a tuple."
            )

        for exception in self.availability_exceptions:
            if not isinstance(exception, AvailabilityException):
                raise ValueError(
                    "Availability exceptions must contain "
                    "AvailabilityException objects."
                )

        # Reject duplicate exception dates.
        exception_dates = [
            exception.date
            for exception in self.availability_exceptions
        ]

        if len(exception_dates) != len(set(exception_dates)):
            raise ValueError(
                "Duplicate availability exception dates detected."
            )

        if (
            self.datetime_availability is not None
            and (
                self.weekly_availability
                or self.availability_exceptions
            )
        ):
            raise ValueError(
                "Cannot combine datetime availability with "
                "weekly availability or exceptions."
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
class FixedAssignment:
    employee_id: int
    shift: DateTimeShift

    def __post_init__(self):
        if type(self.employee_id) is not int or self.employee_id <= 0:
            raise ValueError(
                "Fixed assignment employee ID must be positive."
            )

        if not isinstance(self.shift, DateTimeShift):
            raise ValueError(
                "Fixed assignment must contain a DateTimeShift."
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