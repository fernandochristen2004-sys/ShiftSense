"""Managing a restaurant's staff: roles (skills) and employees.

Like the other services, these change the session but never commit.

Hours are whole hours here, as in the engine (see docs/limitations.md);
the database stores minutes.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import models as db
from services.errors import ConflictError
from services.loading import load_restaurant

UNSET = object()  # "not sent", as opposed to None ("clear it")


@dataclass(frozen=True)
class StaffMember:
    """An employee row with their role names, sorted."""

    employee: db.Employee
    skills: tuple[str, ...]


# Roles

def list_skills(session: Session, restaurant_id: int) -> list[db.Skill]:
    load_restaurant(session, restaurant_id)
    return list(session.scalars(
        select(db.Skill).where(db.Skill.restaurant_id == restaurant_id).order_by(db.Skill.name)
    ))


def create_skill(session: Session, restaurant_id: int, name: str) -> db.Skill:
    """Add a role such as "barista". Names are stored lower-case."""
    load_restaurant(session, restaurant_id)
    name = clean_name(name, "Role name")
    if skill_ids(session, restaurant_id, [name]):
        raise ConflictError(f'The role "{name}" already exists.')

    skill = db.Skill(restaurant_id=restaurant_id, name=name)
    session.add(skill)
    session.flush()
    return skill


def clean_name(name: str, what: str) -> str:
    cleaned = " ".join(name.split()).lower()
    if not cleaned:
        raise ValueError(f"{what} can't be blank.")
    return cleaned


def skill_ids(session: Session, restaurant_id: int, names) -> dict[str, int]:
    return dict(session.execute(
        select(db.Skill.name, db.Skill.id).where(
            db.Skill.restaurant_id == restaurant_id, db.Skill.name.in_(list(names))
        )
    ).all())


# Employees

def list_staff(
    session: Session, restaurant_id: int, include_inactive: bool = False
) -> list[StaffMember]:
    load_restaurant(session, restaurant_id)
    query = select(db.Employee).where(db.Employee.restaurant_id == restaurant_id)
    if not include_inactive:
        query = query.where(db.Employee.status == "active")
    employees = session.scalars(query.order_by(db.Employee.display_name, db.Employee.id)).all()

    skills = _skills_by_employee(session, [e.id for e in employees])
    return [StaffMember(e, skills.get(e.id, ())) for e in employees]


def get_staff_member(session: Session, restaurant_id: int, employee_id: int) -> StaffMember:
    employee = _employee(session, restaurant_id, employee_id)
    return StaffMember(employee, _skills_by_employee(session, [employee.id]).get(employee.id, ()))


def create_employee(
    session: Session,
    restaurant_id: int,
    *,
    display_name: str,
    max_hours: int,
    skills: list[str],
    target_hours: float | None = None,
    employee_number: str | None = None,
    phone: str | None = None,
) -> StaffMember:
    load_restaurant(session, restaurant_id)
    role_ids = _resolve_skills(session, restaurant_id, skills)  # check before saving anything
    employee = db.Employee(restaurant_id=restaurant_id, status="active")
    _apply(
        session, employee,
        display_name=display_name,
        max_hours=max_hours,
        target_hours=target_hours,
        employee_number=employee_number,
        phone=phone,
    )
    session.add(employee)
    session.flush()
    _set_skills(session, employee, role_ids)
    return get_staff_member(session, restaurant_id, employee.id)


def update_employee(
    session: Session, restaurant_id: int, employee_id: int, **changes
) -> StaffMember:
    """Change only the fields given. `skills` replaces the whole list.

    Making someone inactive keeps them out of new drafts and repairs. A
    published schedule they're on stays as it is until the week is repaired;
    the repair then takes them off their shifts.
    """
    employee = _employee(session, restaurant_id, employee_id)
    skills = changes.pop("skills", UNSET)
    role_ids = None if skills is UNSET else _resolve_skills(session, restaurant_id, skills)
    _apply(session, employee, **changes)
    session.flush()
    if role_ids is not None:
        _set_skills(session, employee, role_ids)
    return get_staff_member(session, restaurant_id, employee.id)


def _employee(session: Session, restaurant_id: int, employee_id: int) -> db.Employee:
    employee = session.get(db.Employee, employee_id)
    if employee is None or employee.restaurant_id != restaurant_id:
        raise LookupError(f"Employee {employee_id} not found.")
    return employee


def _apply(
    session: Session,
    employee: db.Employee,
    *,
    display_name=UNSET,
    max_hours=UNSET,
    target_hours=UNSET,
    employee_number=UNSET,
    phone=UNSET,
    status=UNSET,
) -> None:
    # Check everything first, so a refused change leaves the employee untouched.
    name = employee.display_name
    if display_name is not UNSET:
        name = " ".join(display_name.split())
        if not name:
            raise ValueError("Name can't be blank.")

    max_minutes = employee.max_minutes if max_hours is UNSET else max_hours * 60
    target_minutes = employee.target_minutes
    if target_hours is not UNSET:
        target_minutes = None if target_hours is None else round(target_hours * 60)
    if target_minutes is not None and target_minutes > max_minutes:
        raise ValueError(
            f"Target hours ({target_minutes / 60:g}) can't be more than "
            f"max hours ({max_minutes // 60})."
        )

    number = employee.employee_number
    if employee_number is not UNSET:
        number = (employee_number or "").strip() or None
        if number is not None and _number_taken(session, employee, number):
            raise ConflictError(f"Employee number {number} is already used by someone else.")

    employee.display_name = name
    employee.max_minutes = max_minutes
    employee.target_minutes = target_minutes
    employee.employee_number = number

    if phone is not UNSET:
        employee.phone = (phone or "").strip() or None
    if status is not UNSET:
        employee.status = status


def _number_taken(session: Session, employee: db.Employee, number: str) -> bool:
    query = select(func.count()).where(
        db.Employee.restaurant_id == employee.restaurant_id,
        db.Employee.employee_number == number,
    )
    if employee.id is not None:
        query = query.where(db.Employee.id != employee.id)
    return bool(session.scalar(query))


def _resolve_skills(session: Session, restaurant_id: int, names: list[str]) -> set[int]:
    """Role names to ids. Every role must already exist."""
    wanted = {clean_name(name, "Role name") for name in names}
    ids = skill_ids(session, restaurant_id, wanted)
    unknown = sorted(wanted - ids.keys())
    if unknown:
        raise ValueError(
            "Unknown role(s): " + ", ".join(unknown) + ". Add them as roles first."
        )
    return set(ids.values())


def _set_skills(session: Session, employee: db.Employee, ids: set[int]) -> None:
    current = {
        row.skill_id: row
        for row in session.scalars(
            select(db.EmployeeSkill).where(db.EmployeeSkill.employee_id == employee.id)
        )
    }
    for skill_id, row in current.items():
        if skill_id not in ids:
            session.delete(row)
    for skill_id in sorted(ids):
        if skill_id not in current:
            session.add(db.EmployeeSkill(
                restaurant_id=employee.restaurant_id, employee_id=employee.id, skill_id=skill_id,
            ))
    session.flush()


def _skills_by_employee(session: Session, employee_ids: list[int]) -> dict[int, tuple[str, ...]]:
    result: dict[int, list[str]] = {}
    for employee_id, name in session.execute(
        select(db.EmployeeSkill.employee_id, db.Skill.name)
        .join(db.Skill, db.Skill.id == db.EmployeeSkill.skill_id)
        .where(db.EmployeeSkill.employee_id.in_(employee_ids))
        .order_by(db.Skill.name)
    ):
        result.setdefault(employee_id, []).append(name)
    return {k: tuple(v) for k, v in result.items()}
