"""Endpoints for a restaurant's staff: roles (skills) and employees.

Error codes are listed in api/errors.py.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from api.deps import get_session
from api.errors import error, service_errors
from api.staff_schemas import EmployeeIn, EmployeeOut, EmployeeUpdate, SkillIn, SkillOut
from services.staff import (
    StaffMember,
    create_employee,
    create_skill,
    get_staff_member,
    list_skills,
    list_staff,
    update_employee,
)

router = APIRouter(prefix="/restaurants", tags=["staff"])

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
