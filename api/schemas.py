"""JSON request and response models for the ShiftSense API.

These mirror the engine's dataclasses but are kept separate on purpose: the
API's public format can stay stable while the engine changes inside.
"""

from datetime import date, time

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base model that rejects unknown fields, so typos are caught."""

    model_config = ConfigDict(extra="forbid")


# Requests

class WeeklyAvailabilityIn(ApiModel):
    weekday: int = Field(ge=0, le=6, description="0 = Monday … 6 = Sunday")
    start_time: time
    end_time: time = Field(description="Earlier than start_time means it crosses midnight")


class TimeIntervalIn(ApiModel):
    start_time: time
    end_time: time


class AvailabilityExceptionIn(ApiModel):
    date: date
    available: bool = Field(description="false = off all day; true = only the listed intervals")
    intervals: list[TimeIntervalIn] = []


class DatetimeIntervalIn(ApiModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class EmployeeIn(ApiModel):
    id: int = Field(gt=0)
    name: str = Field(min_length=1)
    skills: list[str]
    max_hours: int = Field(ge=0)
    target_minutes: int | None = Field(default=None, ge=0)
    weekly_availability: list[WeeklyAvailabilityIn] = []
    availability_exceptions: list[AvailabilityExceptionIn] = []
    datetime_availability: list[DatetimeIntervalIn] | None = Field(
        default=None,
        description="Exact intervals. Cannot be combined with weekly availability or exceptions",
    )


class ShiftRequirementIn(ApiModel):
    skill: str = Field(min_length=1)
    count: int = Field(ge=0, description="Target number of people")
    min_count: int | None = Field(default=None, ge=0, description="Defaults to count")


class ShiftIn(ApiModel):
    id: int = Field(gt=0)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    requirements: list[ShiftRequirementIn] = Field(min_length=1)


class PolicyIn(ApiModel):
    minimum_rest_hours: int = Field(default=0, ge=0)
    enforce_minimum_rest: bool = False
    fairness_enabled: bool = True
    allow_split_shifts: bool = False
    split_shift_min_break_minutes: int = Field(default=120, gt=0)
    max_split_span_minutes: int = Field(default=780, gt=0)
    allow_partial_coverage: bool = False


class AssignmentRef(ApiModel):
    """One person working one shift in one role."""

    shift_id: int = Field(gt=0)
    role: str = Field(min_length=1)
    employee_id: int = Field(gt=0)


class ExclusionIn(ApiModel):
    """Keep an employee off a shift."""

    shift_id: int = Field(gt=0)
    employee_id: int = Field(gt=0)


class GenerateRequest(ApiModel):
    employees: list[EmployeeIn]
    shifts: list[ShiftIn]
    policy: PolicyIn = PolicyIn()
    timezone: str = Field(default="UTC", description="IANA name, e.g. Asia/Colombo")
    locked_assignments: list[AssignmentRef] = []
    excluded_assignments: list[ExclusionIn] = []
    deterministic: bool = Field(default=False, description="Same result every run (slower)")


# Responses

class ShortageOut(ApiModel):
    shift_id: int
    role: str
    missing: int


class ScheduleResponse(ApiModel):
    status: str = Field(description="OPTIMAL, FEASIBLE, INFEASIBLE or UNKNOWN")
    assignments: list[AssignmentRef] | None = Field(description="null when no schedule was found")
    fully_covered: bool | None
    shortages: list[ShortageOut]
    conflicts: list[str] = Field(description="Explanations for conflicting locks, if any")
    validation_errors: list[str] = Field(description="Rule violations found by the validator")
    objective_values: dict[str, int]
    stage_statuses: dict[str, str]
    schedule_metrics: dict[str, int | float]
    assignment_changes: int | None = Field(description="Repairs only")
