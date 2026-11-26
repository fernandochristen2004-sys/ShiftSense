"""JSON models for managing staff: roles, employees and availability."""

from datetime import date, time
from typing import Literal

from pydantic import Field

from api.schemas import ApiModel, TimeIntervalIn, WeeklyAvailabilityIn

MAX_WEEKLY_HOURS = 80


class SkillIn(ApiModel):
    name: str = Field(min_length=1, max_length=40, examples=["barista"])


class SkillOut(ApiModel):
    id: int
    name: str


class EmployeeIn(ApiModel):
    display_name: str = Field(min_length=1, max_length=80, examples=["Asha"])
    max_hours: int = Field(ge=0, le=MAX_WEEKLY_HOURS, description="Most hours a week, whole hours")
    target_hours: float | None = Field(
        default=None, ge=0, le=MAX_WEEKLY_HOURS, description="Hours they'd like; spreads work fairly",
    )
    skills: list[str] = Field(default_factory=list, examples=[["cook", "server"]])
    employee_number: str | None = Field(default=None, max_length=40)
    phone: str | None = Field(default=None, max_length=40)


class EmployeeUpdate(ApiModel):
    """Send only what changes. `skills` replaces the whole list; null clears a field."""

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    max_hours: int | None = Field(default=None, ge=0, le=MAX_WEEKLY_HOURS)
    target_hours: float | None = Field(default=None, ge=0, le=MAX_WEEKLY_HOURS)
    skills: list[str] | None = None
    employee_number: str | None = Field(default=None, max_length=40)
    phone: str | None = Field(default=None, max_length=40)
    status: Literal["active", "inactive"] | None = Field(
        default=None, description="inactive = kept out of new schedules and repairs",
    )


class EmployeeOut(ApiModel):
    id: int
    display_name: str
    status: str
    max_hours: int
    target_hours: float | None
    skills: list[str]
    employee_number: str | None
    phone: str | None


# Availability

class WeeklyHoursIn(ApiModel):
    """Replaces all of someone's weekly hours. An empty list means never available."""

    rules: list[WeeklyAvailabilityIn] = Field(
        max_length=50,
        examples=[[
            {"weekday": 0, "start_time": "10:00", "end_time": "23:00"},
            {"weekday": 4, "start_time": "16:00", "end_time": "02:00"},
        ]],
    )


class DateExceptionIn(ApiModel):
    available: bool = Field(
        description="false = off all day; true = only the windows listed in intervals",
    )
    intervals: list[TimeIntervalIn] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=200, examples=["Exam"])


class WeeklyRuleOut(ApiModel):
    weekday: int = Field(description="0 = Monday … 6 = Sunday")
    start_time: time
    end_time: time = Field(description="Earlier than start_time means it crosses midnight")


class TimeIntervalOut(ApiModel):
    start_time: time
    end_time: time


class DateExceptionOut(ApiModel):
    date: date
    available: bool
    intervals: list[TimeIntervalOut]
    note: str | None


class AvailabilityOut(ApiModel):
    employee_id: int
    weekly: list[WeeklyRuleOut]
    exceptions: list[DateExceptionOut]
