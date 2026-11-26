"""Endpoints that work with a restaurant's stored data.

The flagship flow: generate a draft → publish it → record a call-out →
repair the week → publish the repair.

Errors come back as {"detail": {"code": ..., "message": ...}} so a
dashboard can react to the code:
    404 not_found               restaurant, schedule or shift doesn't exist
    409 stale                   someone changed the schedule; reload
    409 shortages_not_accepted  ask the manager to confirm, then resend
    422 invalid                 the request breaks a rule
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from api.convert import schedule_changes
from api.deps import get_session
from api.schemas import ShortageOut
from api.stored_schemas import (
    CalloutOut,
    CalloutRiskOut,
    DraftRequest,
    DraftResponse,
    PublishRequest,
    RequirementOut,
    RestaurantOut,
    RiskReportOut,
    ScheduleDetail,
    ScheduleSummary,
    ShiftOut,
    StoredAssignmentOut,
    StoredCalloutIn,
)
from db import models as db
from services.loading import load_restaurant
from services.explanations import explain_recorded_callouts
from services.risk import callout_risk
from services.scheduling import (
    DraftOutcome,
    ShortagesNotAcceptedError,
    StaleScheduleError,
    cancel_absence,
    current_published,
    generate_draft,
    publish_schedule,
    record_absence,
    repair_published,
)
from services.weeks import week_bounds

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


# Errors

def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@contextmanager
def _service_errors() -> Iterator[None]:
    """Turn service exceptions into HTTP errors. Order matters: specific first."""
    try:
        yield
    except LookupError as error:
        raise _error(404, "not_found", str(error)) from error
    except ShortagesNotAcceptedError as error:
        raise _error(409, "shortages_not_accepted", str(error)) from error
    except StaleScheduleError as error:
        raise _error(409, "stale", str(error)) from error
    except (StaleDataError, IntegrityError) as error:
        # Another request changed or published this week at the same moment.
        raise _error(
            409, "stale", "The schedule was changed by someone else. Reload and try again."
        ) from error
    except ValueError as error:
        raise _error(422, "invalid", str(error)) from error


# Building responses

def _summary_fields(schedule: db.Schedule) -> dict:
    return {
        "id": schedule.id,
        "revision_number": schedule.revision_number,
        "status": schedule.status,
        "row_version": schedule.row_version,
        "based_on_id": schedule.based_on_id,
        "period_start": schedule.period_start,
        "period_end": schedule.period_end,
        "solver_status": schedule.solver_status,
        "fully_covered": schedule.fully_covered,
        "shortages": [ShortageOut(**shortage) for shortage in schedule.shortages],
        "assignment_changes": schedule.assignment_changes,
        "created_at": schedule.created_at,
        "published_at": schedule.published_at,
    }


def _assignments(session: Session, schedule_id: int) -> list[tuple[int, str, int, str]]:
    return session.execute(
        select(db.Assignment.shift_id, db.Skill.name, db.Employee.id, db.Employee.display_name)
        .join(db.Skill, db.Skill.id == db.Assignment.skill_id)
        .join(db.Employee, db.Employee.id == db.Assignment.employee_id)
        .where(db.Assignment.schedule_id == schedule_id)
        .order_by(db.Assignment.shift_id, db.Skill.name, db.Employee.id)
    ).all()


def _as_engine_format(rows) -> dict[int, dict[str, list[int]]]:
    schedule: dict[int, dict[str, list[int]]] = {}
    for shift_id, role, employee_id, _ in rows:
        schedule.setdefault(shift_id, {}).setdefault(role, []).append(employee_id)
    return schedule


def _detail(session: Session, schedule: db.Schedule) -> ScheduleDetail:
    rows = _assignments(session, schedule.id)

    changes = None
    if schedule.based_on_id is not None:
        before = _as_engine_format(_assignments(session, schedule.based_on_id))
        changes = schedule_changes(before, _as_engine_format(rows))

    return ScheduleDetail(
        **_summary_fields(schedule),
        assignments=[
            StoredAssignmentOut(
                shift_id=shift_id, role=role, employee_id=employee_id, employee_name=name,
            )
            for shift_id, role, employee_id, name in rows
        ],
        changes=changes,
        objective_values=dict(schedule.objective_values),
        schedule_metrics=dict(schedule.schedule_metrics),
    )


def _draft_response(session: Session, outcome: DraftOutcome) -> DraftResponse:
    result = outcome.result
    return DraftResponse(
        status=result.status,
        conflicts=list(result.conflicts),
        stage_statuses=dict(result.stage_statuses or {}),
        schedule=_detail(session, outcome.schedule) if outcome.schedule else None,
    )


def _callout_out(absence: db.Absence) -> CalloutOut:
    return CalloutOut(
        id=absence.id,
        shift_id=absence.shift_id,
        employee_id=absence.employee_id,
        rest_of_day=absence.rest_of_day,
        note=absence.note,
        reported_at=absence.reported_at,
    )


# Lookups

def _restaurant_week(session: Session, restaurant_id: int, week_start: date):
    restaurant = load_restaurant(session, restaurant_id)
    return week_bounds(week_start, ZoneInfo(restaurant.timezone))


def _schedule(session: Session, restaurant_id: int, schedule_id: int) -> db.Schedule:
    """A schedule, but only if it belongs to this restaurant."""
    schedule = session.get(db.Schedule, schedule_id)
    if schedule is None or schedule.restaurant_id != restaurant_id:
        raise LookupError(f"Schedule {schedule_id} not found.")
    return schedule


# Restaurants and their weeks

def _restaurant_out(restaurant: db.Restaurant) -> RestaurantOut:
    return RestaurantOut(id=restaurant.id, name=restaurant.name, timezone=restaurant.timezone)


@router.get("", response_model=list[RestaurantOut])
def list_restaurants(session: Session = Depends(get_session)) -> list[RestaurantOut]:
    """Every restaurant, oldest first."""
    restaurants = session.scalars(select(db.Restaurant).order_by(db.Restaurant.id)).all()
    return [_restaurant_out(restaurant) for restaurant in restaurants]


@router.get("/{restaurant_id}", response_model=RestaurantOut)
def get_restaurant(
    restaurant_id: int,
    session: Session = Depends(get_session),
) -> RestaurantOut:
    with _service_errors():
        return _restaurant_out(load_restaurant(session, restaurant_id))


@router.get("/{restaurant_id}/weeks/{week_start}/shifts", response_model=list[ShiftOut])
def list_shifts(
    restaurant_id: int,
    week_start: date,
    session: Session = Depends(get_session),
) -> list[ShiftOut]:
    """Active shifts starting in the week, in order, with local times and roles."""
    with _service_errors():
        restaurant = load_restaurant(session, restaurant_id)
        period_start, period_end = week_bounds(week_start, ZoneInfo(restaurant.timezone))
    local = ZoneInfo(restaurant.timezone)

    shifts = session.scalars(
        select(db.Shift)
        .where(
            db.Shift.restaurant_id == restaurant_id,
            db.Shift.status == "active",
            db.Shift.starts_at >= period_start,
            db.Shift.starts_at < period_end,
        )
        .order_by(db.Shift.starts_at, db.Shift.id)
    ).all()

    requirements: dict[int, list[RequirementOut]] = {shift.id: [] for shift in shifts}
    for shift_id, role, count, min_count in session.execute(
        select(
            db.ShiftRequirement.shift_id,
            db.Skill.name,
            db.ShiftRequirement.count,
            db.ShiftRequirement.min_count,
        )
        .join(db.Skill, db.Skill.id == db.ShiftRequirement.skill_id)
        .where(db.ShiftRequirement.shift_id.in_(list(requirements)))
        .order_by(db.ShiftRequirement.shift_id, db.Skill.name)
    ):
        requirements[shift_id].append(RequirementOut(role=role, count=count, min_count=min_count))

    result = []
    for shift in shifts:
        starts, ends = shift.starts_at.astimezone(local), shift.ends_at.astimezone(local)
        result.append(ShiftOut(
            id=shift.id,
            label=shift.label,
            starts_at=shift.starts_at,
            ends_at=shift.ends_at,
            local_date=starts.date(),
            local_start=starts.time(),
            local_end=ends.time(),
            requirements=requirements[shift.id],
        ))
    return result


# Schedules

@router.post("/{restaurant_id}/weeks/{week_start}/drafts", response_model=DraftResponse)
def create_draft(
    restaurant_id: int,
    week_start: date,
    request: DraftRequest = DraftRequest(),
    session: Session = Depends(get_session),
) -> DraftResponse:
    """Generate a new draft for a week (Monday) from the stored data.

    An impossible week is not an error: it returns 200 with status
    INFEASIBLE and `schedule: null`, and nothing is saved.
    """
    with _service_errors():
        outcome = generate_draft(session, restaurant_id, week_start, request.deterministic)
        response = _draft_response(session, outcome)
    session.commit()
    return response


@router.get("/{restaurant_id}/weeks/{week_start}/schedules", response_model=list[ScheduleSummary])
def list_schedules(
    restaurant_id: int,
    week_start: date,
    session: Session = Depends(get_session),
) -> list[ScheduleSummary]:
    """Every revision of a week, newest first."""
    with _service_errors():
        period_start, _ = _restaurant_week(session, restaurant_id, week_start)

    schedules = session.scalars(
        select(db.Schedule)
        .where(
            db.Schedule.restaurant_id == restaurant_id,
            db.Schedule.period_start == period_start,
        )
        .order_by(db.Schedule.revision_number.desc())
    ).all()
    return [ScheduleSummary(**_summary_fields(schedule)) for schedule in schedules]


@router.get("/{restaurant_id}/weeks/{week_start}/published", response_model=ScheduleDetail)
def get_published(
    restaurant_id: int,
    week_start: date,
    session: Session = Depends(get_session),
) -> ScheduleDetail:
    """The week's live schedule. 404 if nothing is published yet."""
    with _service_errors():
        period_start, _ = _restaurant_week(session, restaurant_id, week_start)
        published = current_published(session, restaurant_id, period_start)
        if published is None:
            raise LookupError("Nothing is published for that week yet.")
    return _detail(session, published)


@router.get("/{restaurant_id}/schedules/{schedule_id}", response_model=ScheduleDetail)
def get_schedule(
    restaurant_id: int,
    schedule_id: int,
    session: Session = Depends(get_session),
) -> ScheduleDetail:
    """One revision with its assignments and, for repairs, what changed."""
    with _service_errors():
        schedule = _schedule(session, restaurant_id, schedule_id)
    return _detail(session, schedule)


@router.post("/{restaurant_id}/schedules/{schedule_id}/publish", response_model=ScheduleDetail)
def publish(
    restaurant_id: int,
    schedule_id: int,
    request: PublishRequest,
    session: Session = Depends(get_session),
) -> ScheduleDetail:
    """Publish a draft. The week's previous published revision is archived."""
    with _service_errors():
        _schedule(session, restaurant_id, schedule_id)
        schedule = publish_schedule(
            session,
            schedule_id,
            request.expected_row_version,
            accept_shortages=request.accept_shortages,
        )
        session.commit()
    return _detail(session, schedule)


# Call-outs and repairs

@router.post(
    "/{restaurant_id}/callouts", response_model=CalloutOut, status_code=status.HTTP_201_CREATED
)
def create_callout(
    restaurant_id: int,
    request: StoredCalloutIn,
    session: Session = Depends(get_session),
) -> CalloutOut:
    """Record that someone can't work a shift they're published on.

    This only records it. Call /weeks/{week_start}/repair to find cover.
    """
    with _service_errors():
        absence = record_absence(
            session,
            restaurant_id,
            request.employee_id,
            request.shift_id,
            rest_of_day=request.rest_of_day,
            note=request.note,
        )
        session.commit()
    session.refresh(absence)  # load reported_at, set by the database
    return _callout_out(absence)


@router.get("/{restaurant_id}/weeks/{week_start}/callouts", response_model=list[CalloutOut])
def list_callouts(
    restaurant_id: int,
    week_start: date,
    session: Session = Depends(get_session),
) -> list[CalloutOut]:
    """Call-outs for shifts starting in the week, oldest first."""
    with _service_errors():
        period_start, period_end = _restaurant_week(session, restaurant_id, week_start)

    absences = session.scalars(
        select(db.Absence)
        .join(db.Shift, db.Shift.id == db.Absence.shift_id)
        .where(
            db.Absence.restaurant_id == restaurant_id,
            db.Shift.starts_at >= period_start,
            db.Shift.starts_at < period_end,
        )
        .order_by(db.Absence.id)
    ).all()
    return [_callout_out(absence) for absence in absences]


@router.delete(
    "/{restaurant_id}/callouts/{callout_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_callout(
    restaurant_id: int,
    callout_id: int,
    session: Session = Depends(get_session),
) -> None:
    """Cancel a recorded call-out. Repairs from now on ignore it."""
    with _service_errors():
        cancel_absence(session, restaurant_id, callout_id)
        session.commit()


@router.post("/{restaurant_id}/weeks/{week_start}/repair", response_model=DraftResponse)
def repair_week(
    restaurant_id: int,
    week_start: date,
    request: DraftRequest = DraftRequest(),
    session: Session = Depends(get_session),
) -> DraftResponse:
    """Repair the published week around every recorded call-out.

    The repair is saved as a draft; `schedule.changes` lists what moved.
    The published schedule stays live until the repair is published.
    """
    with _service_errors():
        outcome = repair_published(session, restaurant_id, week_start, request.deterministic)
        response = _draft_response(session, outcome)
        if outcome.schedule is None:
            response.explanation = explain_recorded_callouts(session, restaurant_id, week_start)
    session.commit()
    return response


@router.get("/{restaurant_id}/weeks/{week_start}/risk", response_model=RiskReportOut)
def get_callout_risk(
    restaurant_id: int,
    week_start: date,
    session: Session = Depends(get_session),
) -> RiskReportOut:
    """What happens if each scheduled person calls out.

    Simulates a call-out for every assignment in the published week and runs
    a repair for each. Takes a few seconds; nothing is saved.
    """
    with _service_errors():
        report = callout_risk(session, restaurant_id, week_start)

    names = dict(session.execute(
        select(db.Employee.id, db.Employee.display_name)
        .where(db.Employee.restaurant_id == restaurant_id)
    ).all())
    return RiskReportOut(
        schedule_id=report.schedule_id,
        week_fixable=report.week_fixable,
        blocker=report.blocker,
        baseline_missing=report.baseline_missing,
        checked=len(report.risks),
        at_risk=len(report.at_risk),
        risks=[
            CalloutRiskOut(
                shift_id=risk.shift_id,
                employee_id=risk.employee_id,
                employee_name=names.get(risk.employee_id, f"#{risk.employee_id}"),
                role=risk.role,
                level=risk.level,
                extra_missing=risk.extra_missing,
                changes=risk.changes,
                reason=risk.reason,
            )
            for risk in report.risks
        ],
    )
