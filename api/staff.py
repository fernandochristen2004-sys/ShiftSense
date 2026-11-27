"""Endpoints for a restaurant's staff: roles (skills), employees and availability.

Error codes are listed in api/errors.py.
"""

from datetime import date

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from api.auth import require_restaurant_access
from api.deps import get_session
from api.errors import error, service_errors
from api.staff_schemas import (
    AvailabilityOut,
    DateExceptionIn,
    DateExceptionOut,
    EmployeeIn,
    EmployeeOut,
    EmployeeUpdate,
    SkillIn,
    SkillOut,
    TimeIntervalOut,
    WeeklyHoursIn,
    WeeklyRuleOut,
)
from services.availability import (
    Availability,
    get_availability,
    remove_exception,
    replace_weekly,
    set_exception,
)
from services.staff import (
    StaffMember,
    create_employee,
    create_skill,
    get_staff_member,
    list_skills,
    list_staff,
    update_employee,
)

router = APIRouter(
    prefix="/restaurants",
    tags=["staff"],
    dependencies=[Depends(require_restaurant_access)],  # members only
)

# A field that must have a value: null makes no sense for it.
REQUIRED_ON_UPDATE = ("display_name", "max_hours", "skills", "status")


def _employee_out(member: StaffMember) -> EmployeeOut:
    e = member.employee
    return EmployeeOut(
        id=e.id,
        display_name=e.display_name,
        status=e.status,
        max_hours=e.max_minutes // 60,
        target_hours=None if e.target_minutes is None else e.target_minutes / 60,
        skills=list(member.skills),
        employee_number=e.employee_number,
        phone=e.phone,
    )


# Roles

@router.get("/{restaurant_id}/skills", response_model=list[SkillOut])
def get_skills(restaurant_id: int, session: Session = Depends(get_session)) -> list[SkillOut]:
    """The restaurant's roles, A to Z."""
    with service_errors():
        return [SkillOut(id=s.id, name=s.name) for s in list_skills(session, restaurant_id)]


@router.post(
    "/{restaurant_id}/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED,
)
def add_skill(
    restaurant_id: int, request: SkillIn, session: Session = Depends(get_session)
) -> SkillOut:
    """Add a role. Names are stored lower-case; duplicates are a 409 conflict."""
    with service_errors():
        skill = create_skill(session, restaurant_id, request.name)
        session.commit()
        return SkillOut(id=skill.id, name=skill.name)


# Employees

@router.get("/{restaurant_id}/employees", response_model=list[EmployeeOut])
def get_employees(
    restaurant_id: int,
    include_inactive: bool = False,
    session: Session = Depends(get_session),
) -> list[EmployeeOut]:
    """Staff A to Z. Inactive people are left out unless asked for."""
    with service_errors():
        return [_employee_out(m) for m in list_staff(session, restaurant_id, include_inactive)]


@router.get("/{restaurant_id}/employees/{employee_id}", response_model=EmployeeOut)
def get_employee(
    restaurant_id: int, employee_id: int, session: Session = Depends(get_session)
) -> EmployeeOut:
    with service_errors():
        return _employee_out(get_staff_member(session, restaurant_id, employee_id))


@router.post(
    "/{restaurant_id}/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED,
)
def add_employee(
    restaurant_id: int, request: EmployeeIn, session: Session = Depends(get_session)
) -> EmployeeOut:
    """Add someone. Their roles must already exist (see /skills)."""
    with service_errors():
        member = create_employee(session, restaurant_id, **request.model_dump())
        session.commit()
        return _employee_out(member)


@router.patch("/{restaurant_id}/employees/{employee_id}", response_model=EmployeeOut)
def edit_employee(
    restaurant_id: int,
    employee_id: int,
    request: EmployeeUpdate,
    session: Session = Depends(get_session),
) -> EmployeeOut:
    """Change some of someone's details. Set status to inactive when they leave.

    An inactive person stays on a published schedule until the week is
    repaired; the repair takes them off their shifts.
    """
    changes = request.model_dump(include=request.model_fields_set)
    cleared = [name for name in REQUIRED_ON_UPDATE if name in changes and changes[name] is None]
    if cleared:
        raise error(422, "invalid", f"{cleared[0]} can't be null.")

    with service_errors():
        member = update_employee(session, restaurant_id, employee_id, **changes)
        session.commit()
        return _employee_out(member)


# Availability

def _availability_out(employee_id: int, availability: Availability) -> AvailabilityOut:
    return AvailabilityOut(
        employee_id=employee_id,
        weekly=[
            WeeklyRuleOut(weekday=r.weekday, start_time=r.start_time, end_time=r.end_time)
            for r in availability.weekly
        ],
        exceptions=[
            DateExceptionOut(
                date=e.date,
                available=e.available,
                intervals=[TimeIntervalOut(start_time=a, end_time=b) for a, b in e.intervals],
                note=e.note,
            )
            for e in availability.exceptions
        ],
    )


AVAILABILITY = "/{restaurant_id}/employees/{employee_id}/availability"


@router.get(AVAILABILITY, response_model=AvailabilityOut)
def get_employee_availability(
    restaurant_id: int, employee_id: int, session: Session = Depends(get_session)
) -> AvailabilityOut:
    """Weekly hours (restaurant time) and date exceptions."""
    with service_errors():
        return _availability_out(employee_id, get_availability(session, restaurant_id, employee_id))


@router.put(AVAILABILITY + "/weekly", response_model=AvailabilityOut)
def set_weekly_hours(
    restaurant_id: int,
    employee_id: int,
    request: WeeklyHoursIn,
    session: Session = Depends(get_session),
) -> AvailabilityOut:
    """Replace someone's weekly hours. Date exceptions are kept.

    A rule ending earlier than it starts (16:00-02:00) crosses midnight.
    """
    with service_errors():
        availability = replace_weekly(
            session, restaurant_id, employee_id,
            [(r.weekday, r.start_time, r.end_time) for r in request.rules],
        )
        session.commit()
        return _availability_out(employee_id, availability)


@router.put(AVAILABILITY + "/exceptions/{local_date}", response_model=AvailabilityOut)
def set_date_exception(
    restaurant_id: int,
    employee_id: int,
    local_date: date,
    request: DateExceptionIn,
    session: Session = Depends(get_session),
) -> AvailabilityOut:
    """Override the weekly hours on one date (restaurant time).

    {"available": false} = off all day. {"available": true, "intervals": [...]}
    = only those same-day windows. Sending it again replaces it.
    """
    with service_errors():
        availability = set_exception(
            session, restaurant_id, employee_id, local_date,
            available=request.available,
            intervals=[(i.start_time, i.end_time) for i in request.intervals],
            note=request.note,
        )
        session.commit()
        return _availability_out(employee_id, availability)


@router.delete(
    AVAILABILITY + "/exceptions/{local_date}", status_code=status.HTTP_204_NO_CONTENT,
)
def delete_date_exception(
    restaurant_id: int,
    employee_id: int,
    local_date: date,
    session: Session = Depends(get_session),
) -> Response:
    """Remove a date exception, so the weekly hours apply again."""
    with service_errors():
        remove_exception(session, restaurant_id, employee_id, local_date)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
