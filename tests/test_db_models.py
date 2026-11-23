"""Database rules for restaurants, employees and skills (docs/schema.md)."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import Employee, EmployeeSkill, Restaurant, Skill


def _restaurant(db, name="Lanka Bistro"):
    restaurant = Restaurant(name=name, timezone="Asia/Colombo")
    db.add(restaurant)
    db.flush()
    return restaurant


def _employee(db, restaurant, **fields):
    values = {"display_name": "Asha", "max_minutes": 40 * 60}
    values.update(fields)
    employee = Employee(restaurant_id=restaurant.id, **values)
    db.add(employee)
    db.flush()
    return employee


def _skill(db, restaurant, name="server"):
    skill = Skill(restaurant_id=restaurant.id, name=name)
    db.add(skill)
    db.flush()
    return skill


def _rejected(db, make):
    """Assert that the database rejects what `make` adds."""
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            make()
            db.flush()


# Basic records

def test_restaurant_employee_and_skill_are_saved(db):
    restaurant = _restaurant(db)
    employee = _employee(db, restaurant, target_minutes=30 * 60)
    skill = _skill(db, restaurant)
    db.add(EmployeeSkill(restaurant_id=restaurant.id, employee_id=employee.id, skill_id=skill.id))
    db.flush()

    saved = db.scalars(select(EmployeeSkill)).one()
    assert (saved.employee_id, saved.skill_id) == (employee.id, skill.id)
    assert employee.status == "active"
    assert employee.created_at is not None


# Employee rules

def test_unknown_status_is_rejected(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: _employee(db, restaurant, status="fired"))


def test_inactive_status_is_allowed(db):
    restaurant = _restaurant(db)
    assert _employee(db, restaurant, status="inactive").status == "inactive"


def test_maximum_must_be_whole_hours_for_now(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: _employee(db, restaurant, max_minutes=37 * 60 + 30))


def test_negative_maximum_is_rejected(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: _employee(db, restaurant, max_minutes=-60))


def test_target_above_maximum_is_rejected(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: _employee(db, restaurant, max_minutes=20 * 60, target_minutes=21 * 60))


def test_target_can_be_empty_or_zero(db):
    restaurant = _restaurant(db)
    assert _employee(db, restaurant, target_minutes=None).target_minutes is None
    assert _employee(db, restaurant, display_name="Ben", target_minutes=0).target_minutes == 0


def test_blank_name_is_rejected(db):
    restaurant = _restaurant(db)
    _rejected(db, lambda: _employee(db, restaurant, display_name="   "))


def test_employee_number_is_unique_within_a_restaurant(db):
    restaurant = _restaurant(db)
    _employee(db, restaurant, employee_number="E-1")
    _rejected(db, lambda: _employee(db, restaurant, display_name="Ben", employee_number="E-1"))


def test_same_employee_number_is_fine_in_another_restaurant(db):
    first, second = _restaurant(db), _restaurant(db, "Harbour Cafe")
    _employee(db, first, employee_number="E-1")
    assert _employee(db, second, employee_number="E-1").id is not None


def test_many_employees_can_have_no_number(db):
    restaurant = _restaurant(db)
    _employee(db, restaurant)
    assert _employee(db, restaurant, display_name="Ben").employee_number is None


# Skill rules

def test_skill_names_are_unique_within_a_restaurant(db):
    restaurant = _restaurant(db)
    _skill(db, restaurant, "cook")
    _rejected(db, lambda: _skill(db, restaurant, "cook"))


def test_same_skill_name_is_fine_in_another_restaurant(db):
    first, second = _restaurant(db), _restaurant(db, "Harbour Cafe")
    _skill(db, first, "cook")
    assert _skill(db, second, "cook").id is not None


# Restaurant boundaries

def test_employee_cannot_get_a_skill_from_another_restaurant(db):
    first, second = _restaurant(db), _restaurant(db, "Harbour Cafe")
    employee = _employee(db, first)
    other_skill = _skill(db, second, "cook")

    _rejected(db, lambda: db.add(EmployeeSkill(
        restaurant_id=first.id, employee_id=employee.id, skill_id=other_skill.id,
    )))
    _rejected(db, lambda: db.add(EmployeeSkill(
        restaurant_id=second.id, employee_id=employee.id, skill_id=other_skill.id,
    )))


# Deletes

def test_deleting_an_employee_removes_their_skills(db):
    restaurant = _restaurant(db)
    employee = _employee(db, restaurant)
    skill = _skill(db, restaurant)
    db.add(EmployeeSkill(restaurant_id=restaurant.id, employee_id=employee.id, skill_id=skill.id))
    db.flush()

    db.delete(employee)
    db.flush()

    assert db.scalars(select(EmployeeSkill)).all() == []


def test_restaurant_with_employees_cannot_be_deleted(db):
    restaurant = _restaurant(db)
    _employee(db, restaurant)

    def delete_restaurant():
        db.delete(restaurant)

    _rejected(db, delete_restaurant)


def test_skill_in_use_cannot_be_deleted(db):
    restaurant = _restaurant(db)
    employee = _employee(db, restaurant)
    skill = _skill(db, restaurant)
    db.add(EmployeeSkill(restaurant_id=restaurant.id, employee_id=employee.id, skill_id=skill.id))
    db.flush()

    def delete_skill():
        db.delete(skill)

    _rejected(db, delete_skill)
