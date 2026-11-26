"""JSON models for the endpoints that work with stored restaurant data."""

from datetime import date, datetime, time

from pydantic import AwareDatetime, Field

from api.schemas import ApiModel, ChangeOut, ShortageOut


# Requests

class DraftRequest(ApiModel):
    deterministic: bool = Field(default=False, description="Same result every run (slower)")


class PublishRequest(ApiModel):
    expected_row_version: int = Field(
        ge=1, description="The row_version you loaded. Publishing is refused if it changed",
    )
    accept_shortages: bool = Field(
        default=False, description="Confirm publishing a schedule that is short-staffed",
    )


class StoredCalloutIn(ApiModel):
    shift_id: int = Field(gt=0)
    employee_id: int = Field(gt=0)
    rest_of_day: bool = Field(
        default=True,
        description="Also keep them off any shift until 06:00 the next morning (restaurant time)",
    )
    note: str | None = Field(default=None, max_length=500)


# Responses

class StoredAssignmentOut(ApiModel):
    shift_id: int
    role: str
    employee_id: int
    employee_name: str


class ScheduleSummary(ApiModel):
    id: int
    revision_number: int
    status: str = Field(description="draft, published or archived")
    row_version: int = Field(description="Send this back when publishing")
    based_on_id: int | None = Field(description="The revision a repair was built from")
    period_start: AwareDatetime
    period_end: AwareDatetime
    solver_status: str | None
    fully_covered: bool | None
    shortages: list[ShortageOut]
    assignment_changes: int | None = Field(description="Repairs only")
    created_at: datetime
    published_at: datetime | None


class ScheduleDetail(ScheduleSummary):
    assignments: list[StoredAssignmentOut]
    changes: list[ChangeOut] | None = Field(
        description="Differences from the revision it was based on; null for new drafts",
    )
    objective_values: dict[str, int]
    schedule_metrics: dict[str, int | float]


class DraftResponse(ApiModel):
    """The engine's outcome and, if a schedule was found, the saved draft."""

    status: str = Field(description="OPTIMAL, FEASIBLE, INFEASIBLE or UNKNOWN")
    conflicts: list[str]
    stage_statuses: dict[str, str]
    schedule: ScheduleDetail | None = Field(description="null when nothing was saved")
    explanation: str | None = Field(
        default=None, description="Repairs only: why the call-outs can't be covered",
    )


class CalloutOut(ApiModel):
    id: int
    shift_id: int
    employee_id: int
    rest_of_day: bool
    note: str | None
    reported_at: datetime


# Restaurant and week data, for the dashboard

class RestaurantOut(ApiModel):
    id: int
    name: str
    timezone: str = Field(description="IANA name; local times below use it")


class RequirementOut(ApiModel):
    role: str
    count: int = Field(description="Target number of people")
    min_count: int = Field(description="Fewest people the shift can run with")


class ShiftOut(ApiModel):
    id: int
    label: str | None
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    local_date: date = Field(description="The day the shift starts, restaurant time")
    local_start: time = Field(description="Restaurant time")
    local_end: time = Field(description="Restaurant time; earlier than local_start if it ends after midnight")
    requirements: list[RequirementOut]


# Call-out risk

class CalloutRiskOut(ApiModel):
    shift_id: int
    employee_id: int
    employee_name: str
    role: str
    level: str = Field(description="covered, short (positions left unfilled) or no_fix")
    extra_missing: int | None = Field(description="Positions left unfilled; null when no fix exists")
    changes: int | None = Field(description="Changes the repair needs; null when no fix exists")
    reason: str | None = Field(description="Why no repair exists (no_fix only)")


class RiskReportOut(ApiModel):
    schedule_id: int
    week_fixable: bool = Field(
        description="False when call-outs already recorded can't be repaired; risks is then empty",
    )
    blocker: str | None = Field(description="Why the week can't be fixed, when week_fixable is false")
    baseline_missing: int = Field(description="Positions already short before any new call-out")
    checked: int = Field(description="Assignments simulated")
    at_risk: int = Field(description="Call-outs that would leave the week worse off")
    risks: list[CalloutRiskOut]
