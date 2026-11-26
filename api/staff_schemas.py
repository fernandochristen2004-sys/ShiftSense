"""JSON models for managing staff: roles and employees."""

from typing import Literal

from pydantic import Field

from api.schemas import ApiModel

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
