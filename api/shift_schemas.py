"""JSON models for managing shifts."""

from datetime import date, datetime, time

from pydantic import Field

from api.schemas import ApiModel


class RequirementIn(ApiModel):
    role: str = Field(min_length=1, examples=["cook"])
    count: int = Field(ge=1, le=50, description="Target number of people")
    min_count: int | None = Field(
        default=None, ge=0, le=50,
        description="Fewest people it can run with; leave out to make every place essential",
    )


class ShiftIn(ApiModel):
    local_date: date = Field(description="The day it starts, restaurant time", examples=["2026-11-30"])
    start_time: time = Field(examples=["07:00"])
    end_time: time = Field(description="Earlier than start_time = ends the next day", examples=["11:00"])
    label: str | None = Field(default=None, max_length=60, examples=["Breakfast"])
    requirements: list[RequirementIn] = Field(
        min_length=1, max_length=20,
        examples=[[{"role": "cook", "count": 1}, {"role": "server", "count": 2, "min_count": 1}]],
    )


class ShiftUpdate(ApiModel):
    """Send only what changes. `requirements` replaces the whole list."""

    local_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    label: str | None = Field(default=None, max_length=60)
    requirements: list[RequirementIn] | None = Field(default=None, min_length=1, max_length=20)


class CopyWeekIn(ApiModel):
    from_week: date = Field(description="Monday of the week to copy shifts from")


class TemplateIn(ApiModel):
    name: str = Field(min_length=1, max_length=60, examples=["Normal week"])
    week_start: date = Field(description="Monday of the week whose shifts to save")


class ApplyTemplateIn(ApiModel):
    template_id: int


class TemplateOut(ApiModel):
    id: int
    name: str
    shift_count: int
    created_at: datetime
