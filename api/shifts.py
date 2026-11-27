"""Endpoints for a restaurant's shifts and their staffing needs.

Error codes are listed in api/errors.py.
"""

from datetime import date, tzinfo
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_restaurant_access
from api.deps import get_session
from api.errors import error, service_errors
from api.shift_schemas import (
    ApplyTemplateIn,
    CopyWeekIn,
    RequirementIn,
    ShiftIn,
    ShiftUpdate,
    TemplateIn,
    TemplateOut,
)
from api.stored_schemas import RequirementOut, ShiftOut
from db import models as db
from services.loading import load_restaurant
from services.shifts import Need, create_shift, remove_shift, shift_needs, update_shift
from services.week_plans import (
    apply_template,
    copy_week,
    delete_template,
    list_templates,
    save_template,
)
from services.weeks import week_bounds

router = APIRouter(
    prefix="/restaurants",
    tags=["shifts"],
    dependencies=[Depends(require_restaurant_access)],  # members only
)

REQUIRED_ON_UPDATE = ("local_date", "start_time", "end_time", "requirements")


def shift_outs(session: Session, shifts: list[db.Shift], tz: tzinfo) -> list[ShiftOut]:
    needs = shift_needs(session, [shift.id for shift in shifts])
    result = []
    for shift in shifts:
        starts, ends = shift.starts_at.astimezone(tz), shift.ends_at.astimezone(tz)
        result.append(ShiftOut(
            id=shift.id,
            label=shift.label,
            starts_at=shift.starts_at,
            ends_at=shift.ends_at,
            local_date=starts.date(),
            local_start=starts.time(),
            local_end=ends.time(),
            requirements=[
                RequirementOut(role=n.role, count=n.count, min_count=n.min_count)
                for n in needs[shift.id]
            ],
        ))
    return result


def _needs(requirements: list[RequirementIn]) -> list[Need]:
    return [Need(r.role, r.count, r.min_count) for r in requirements]


def _one(session: Session, restaurant_id: int, shift: db.Shift) -> ShiftOut:
    tz = ZoneInfo(load_restaurant(session, restaurant_id).timezone)
    return shift_outs(session, [shift], tz)[0]


@router.get("/{restaurant_id}/weeks/{week_start}/shifts", response_model=list[ShiftOut])
def list_shifts(
    restaurant_id: int,
    week_start: date,
    session: Session = Depends(get_session),
) -> list[ShiftOut]:
    """Active shifts starting in the week, in order, with local times and roles."""
    with service_errors():
        tz = ZoneInfo(load_restaurant(session, restaurant_id).timezone)
        period_start, period_end = week_bounds(week_start, tz)

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
    return shift_outs(session, list(shifts), tz)


@router.post(
    "/{restaurant_id}/shifts", response_model=ShiftOut, status_code=status.HTTP_201_CREATED,
)
def add_shift(
    restaurant_id: int, request: ShiftIn, session: Session = Depends(get_session)
) -> ShiftOut:
    """Add a shift in restaurant time. Its roles must already exist.

    If its week is already published, the shift starts unstaffed; repair the
    week to fill it.
    """
    with service_errors():
        shift = create_shift(
            session, restaurant_id,
            local_date=request.local_date,
            start_time=request.start_time,
            end_time=request.end_time,
            needs=_needs(request.requirements),
            label=request.label,
        )
        session.commit()
        return _one(session, restaurant_id, shift)


@router.patch("/{restaurant_id}/shifts/{shift_id}", response_model=ShiftOut)
def edit_shift(
    restaurant_id: int,
    shift_id: int,
    request: ShiftUpdate,
    session: Session = Depends(get_session),
) -> ShiftOut:
    """Change a shift. Times and staffing are locked (409) once it's been published."""
    changes = request.model_dump(include=request.model_fields_set)
    cleared = [name for name in REQUIRED_ON_UPDATE if name in changes and changes[name] is None]
    if cleared:
        raise error(422, "invalid", f"{cleared[0]} can't be null.")
    if "requirements" in changes:
        changes["needs"] = _needs(request.requirements)
        del changes["requirements"]

    with service_errors():
        shift = update_shift(session, restaurant_id, shift_id, **changes)
        session.commit()
        return _one(session, restaurant_id, shift)


@router.delete("/{restaurant_id}/shifts/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift(
    restaurant_id: int, shift_id: int, session: Session = Depends(get_session)
) -> Response:
    """Take a shift off the rota.

    Unused shifts are deleted. Shifts on a schedule are cancelled instead, so
    older revisions still make sense; repair the week to take staff off it.
    """
    with service_errors():
        remove_shift(session, restaurant_id, shift_id)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Starting a week from another one

def _created(session: Session, restaurant_id: int, shifts: list[db.Shift]) -> list[ShiftOut]:
    tz = ZoneInfo(load_restaurant(session, restaurant_id).timezone)
    return shift_outs(session, shifts, tz)


@router.post(
    "/{restaurant_id}/weeks/{week_start}/copy-shifts",
    response_model=list[ShiftOut],
    status_code=status.HTTP_201_CREATED,
)
def copy_shifts(
    restaurant_id: int,
    week_start: date,
    request: CopyWeekIn,
    session: Session = Depends(get_session),
) -> list[ShiftOut]:
    """Copy another week's shifts and their needs (not who works them) into this empty week.

    A week that already has shifts is a 409 conflict, so nothing is doubled.
    """
    with service_errors():
        shifts = copy_week(session, restaurant_id, request.from_week, week_start)
        session.commit()
        return _created(session, restaurant_id, shifts)


def _template_out(template: db.ShiftTemplate) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        name=template.name,
        shift_count=len(template.shifts),
        created_at=template.created_at,
    )


@router.get("/{restaurant_id}/templates", response_model=list[TemplateOut])
def get_templates(restaurant_id: int, session: Session = Depends(get_session)) -> list[TemplateOut]:
    """Saved weeks of shifts, A to Z."""
    with service_errors():
        return [_template_out(t) for t in list_templates(session, restaurant_id)]


@router.post(
    "/{restaurant_id}/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED,
)
def add_template(
    restaurant_id: int, request: TemplateIn, session: Session = Depends(get_session)
) -> TemplateOut:
    """Save a week's shifts and needs as a template, to start other weeks from."""
    with service_errors():
        template = save_template(session, restaurant_id, request.name, request.week_start)
        session.commit()
        return _template_out(template)


@router.post(
    "/{restaurant_id}/weeks/{week_start}/apply-template",
    response_model=list[ShiftOut],
    status_code=status.HTTP_201_CREATED,
)
def use_template(
    restaurant_id: int,
    week_start: date,
    request: ApplyTemplateIn,
    session: Session = Depends(get_session),
) -> list[ShiftOut]:
    """Fill this empty week with a template's shifts. A week with shifts is a 409 conflict."""
    with service_errors():
        shifts = apply_template(session, restaurant_id, request.template_id, week_start)
        session.commit()
        return _created(session, restaurant_id, shifts)


@router.delete(
    "/{restaurant_id}/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT,
)
def remove_template(
    restaurant_id: int, template_id: int, session: Session = Depends(get_session)
) -> Response:
    """Delete a template. Weeks made from it keep their shifts."""
    with service_errors():
        delete_template(session, restaurant_id, template_id)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
