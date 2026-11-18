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
    target_minutes: int | None = None

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

        # Validate the optional preferred workload target.
        if self.target_minutes is not None:
            if type(self.target_minutes) is not int:
                raise ValueError(
                    "Target minutes must be an integer."
                )

            if self.target_minutes < 0:
                raise ValueError(
                    "Target minutes cannot be negative."
                )

            if self.target_minutes > self.max_hours * 60:
                raise ValueError(
                    "Target minutes cannot exceed maximum working hours."
                )

@dataclass(frozen=True)
class ShiftRequirement:
    skill: str
    count: int
    min_count: int | None = None

    def __post_init__(self):
        if not isinstance(self.skill, str) or not self.skill.strip():
            raise ValueError(
                "Requirement skill cannot be empty."
            )

        if type(self.count) is not int or self.count < 0:
            raise ValueError(
                "Requirement count must be a non-negative integer."
            )

        if self.min_count is not None:
            if (
                type(self.min_count) is not int
                or not 0 <= self.min_count <= self.count
            ):
                raise ValueError(
                    "Requirement minimum count must be an integer "
                    "between zero and the target count."
                )

    @property
    def target_count(self) -> int:
        """Return the desired staffing level."""
        return self.count

    @property
    def effective_min_count(self) -> int:
        """Return the minimum staffing level."""
        if self.min_count is None:
            return self.count
        return self.min_count


@dataclass(frozen=True)
class DateTimeShift:
    id: int
    starts_at: datetime
    ends_at: datetime
    requirements: tuple[ShiftRequirement, ...]

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

        if (
            not isinstance(self.requirements, tuple)
            or not self.requirements
        ):
            raise ValueError(
                "Shift must contain at least one requirement."
            )

        for requirement in self.requirements:
            if not isinstance(requirement, ShiftRequirement):
                raise ValueError(
                    "Shift requirements must contain "
                    "ShiftRequirement objects."
                )

        skills = [
            requirement.skill
            for requirement in self.requirements
        ]

        if len(skills) != len(set(skills)):
            raise ValueError(
                "Duplicate skills in shift requirements."
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
class StaffingShortage:
    shift_id: int
    role: str
    missing: int


@dataclass(frozen=True)
class ScheduleResult:
    status: str
    assignments: dict[int, dict[str, list[int]]] | None
    conflicts: tuple[str, ...] = ()
    objective_values: dict[str, int] | None = None
    stage_statuses: dict[str, str] | None = None
    schedule_metrics: dict[str, int] | None = None
    fully_covered: bool | None = None
    shortages: tuple[StaffingShortage, ...] = ()
    assignment_changes: int | None = None

@dataclass(frozen=True)
class SchedulingPolicy:
    minimum_rest_hours: int = 0
    enforce_minimum_rest: bool = False
    fairness_enabled: bool = True
    allow_split_shifts: bool = False
    split_shift_min_break_minutes: int = 120
    max_split_span_minutes: int = 780
    allow_partial_coverage: bool = False

    def __post_init__(self):
        if type(self.minimum_rest_hours) is not int:
            raise ValueError(
                "Minimum rest hours must be an integer."
            )

        if self.minimum_rest_hours < 0:
            raise ValueError(
                "Minimum rest hours cannot be negative."
            )

        if type(self.enforce_minimum_rest) is not bool:
            raise ValueError(
                "Enforce minimum rest must be a Boolean."
            )

        if type(self.fairness_enabled) is not bool:
            raise ValueError(
                "Fairness enabled must be a Boolean."
            )

        if type(self.allow_split_shifts) is not bool:
            raise ValueError(
                "Allow split shifts must be a Boolean."
            )

        if (
            type(self.split_shift_min_break_minutes) is not int
            or self.split_shift_min_break_minutes <= 0
        ):
            raise ValueError(
                "Split-shift minimum break must be "
                "a positive integer number of minutes."
            )

        if (
            type(self.max_split_span_minutes) is not int
            or self.max_split_span_minutes
            <= self.split_shift_min_break_minutes
        ):
            raise ValueError(
                "Maximum split span must exceed "
                "the minimum split break."
            )

        if (
            self.allow_split_shifts
            and self.enforce_minimum_rest
            and self.split_shift_min_break_minutes
            >= self.minimum_rest_hours * 60
        ):
            raise ValueError(
                "Split-shift minimum break must be shorter "
                "than the normal minimum rest period."
            )

        if type(self.allow_partial_coverage) is not bool:
            raise ValueError(
                "Allow partial coverage must be a Boolean."
            )