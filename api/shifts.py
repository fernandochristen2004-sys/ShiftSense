"""Endpoints for a restaurant's shifts and their staffing needs.

Error codes are listed in api/errors.py.
"""

from datetime import date, tzinfo
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_session
from api.errors import error, service_errors
from api.shift_schemas import RequirementIn, ShiftIn, ShiftUpdate
from api.stored_schemas import RequirementOut, ShiftOut
from db import models as db
from services.loading import load_restaurant
from services.shifts import Need, create_shift, remove_shift, shift_needs, update_shift
from services.weeks import week_bounds

router = APIRouter(prefix="/restaurants", tags=["shifts"])

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
