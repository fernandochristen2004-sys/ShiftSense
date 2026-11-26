"""Tests for managing staff: roles (skills) and employees."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.deps import get_session
from api.main import app
from services.demo import seed_demo_restaurant

MONDAY = date(2026, 11, 23)
WEEK = f"/weeks/{MONDAY.isoformat()}"


@pytest.fixture
def client(db):
    def test_session():
        yield db

    app.dependency_overrides[get_session] = test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def demo(db):
    return seed_demo_restaurant(db, employee_count=25)


@pytest.fixture
def base(demo) -> str:
    return f"/restaurants/{demo.restaurant_id}"


def _new_employee(client, base, **fields) -> dict:
    body = {"display_name": "Noor", "max_hours": 30, "skills": ["server"], **fields}
    response = client.post(base + "/employees", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _code(response) -> str:
    return response.json()["detail"]["code"]


def _published(client, base) -> dict:
    draft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()["schedule"]
    response = client.post(
        base + f"/schedules/{draft['id']}/publish",
        json={"expected_row_version": draft["row_version"], "accept_shortages": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


# Roles

def test_lists_the_restaurants_roles_a_to_z(client, base):
    names = [skill["name"] for skill in client.get(base + "/skills").json()]
    assert names == sorted(names)
    assert {"cook", "server"} <= set(names)


def test_adds_a_role_with_a_tidy_name(client, base):
    response = client.post(base + "/skills", json={"name": "  Pastry   Chef "})
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "pastry chef"
    assert "pastry chef" in [s["name"] for s in client.get(base + "/skills").json()]


def test_a_duplicate_role_is_a_conflict(client, base):
    response = client.post(base + "/skills", json={"name": "COOK"})
    assert response.status_code == 409
    assert _code(response) == "conflict"


def test_a_blank_role_is_invalid(client, base):
    response = client.post(base + "/skills", json={"name": "   "})
    assert response.status_code == 422
    assert _code(response) == "invalid"


def test_roles_of_a_missing_restaurant_are_not_found(client):
    response = client.get("/restaurants/999999/skills")
    assert response.status_code == 404
    assert _code(response) == "not_found"


# Adding and reading employees

def test_lists_active_staff_with_their_roles(client, base):
    staff = client.get(base + "/employees").json()
    assert len(staff) == 25
    assert [e["display_name"] for e in staff] == sorted(e["display_name"] for e in staff)
    assert all(e["status"] == "active" and e["skills"] for e in staff)


def test_adds_an_employee(client, base):
    created = _new_employee(
        client, base, skills=["server", "host"], target_hours=20, employee_number="E-77",
    )
    assert created["display_name"] == "Noor"
    assert created["skills"] == ["host", "server"]
    assert created["max_hours"] == 30
    assert created["target_hours"] == 20
    assert created["status"] == "active"

    fetched = client.get(base + f"/employees/{created['id']}").json()
    assert fetched == created


def test_an_unknown_role_is_invalid_and_nothing_is_saved(client, base):
    response = client.post(
        base + "/employees", json={"display_name": "Noor", "max_hours": 30, "skills": ["juggler"]},
    )
    assert response.status_code == 422
    assert "juggler" in response.json()["detail"]["message"]
    assert "Noor" not in [e["display_name"] for e in client.get(base + "/employees").json()]


def test_target_hours_above_max_hours_is_invalid(client, base):
    response = client.post(
        base + "/employees",
        json={"display_name": "Noor", "max_hours": 20, "target_hours": 25, "skills": []},
    )
    assert response.status_code == 422
    assert "Target hours" in response.json()["detail"]["message"]


def test_max_hours_must_be_whole_and_sensible(client, base):
    for bad in (-1, 81, 12.5):
        response = client.post(
            base + "/employees", json={"display_name": "Noor", "max_hours": bad, "skills": []},
        )
        assert response.status_code == 422, bad


def test_employee_numbers_are_unique_per_restaurant(client, base, db):
    _new_employee(client, base, employee_number="E-1")
    response = client.post(
        base + "/employees",
        json={"display_name": "Sam", "max_hours": 20, "skills": [], "employee_number": "E-1"},
    )
    assert response.status_code == 409
    assert _code(response) == "conflict"

    other = seed_demo_restaurant(db, employee_count=8)
    elsewhere = client.post(
        f"/restaurants/{other.restaurant_id}/employees",
        json={"display_name": "Sam", "max_hours": 20, "skills": [], "employee_number": "E-1"},
    )
    assert elsewhere.status_code == 201


def test_another_restaurants_employee_is_not_found(client, base, db):
    other = seed_demo_restaurant(db, employee_count=8)
    outsider = client.get(f"/restaurants/{other.restaurant_id}/employees").json()[0]

    assert client.get(base + f"/employees/{outsider['id']}").status_code == 404
    response = client.patch(base + f"/employees/{outsider['id']}", json={"max_hours": 10})
    assert response.status_code == 404


def test_another_restaurants_role_cant_be_given(client, base, db):
    other = seed_demo_restaurant(db, employee_count=8)
    client.post(f"/restaurants/{other.restaurant_id}/skills", json={"name": "sommelier"})

    response = client.post(
        base + "/employees", json={"display_name": "Noor", "max_hours": 30, "skills": ["sommelier"]},
    )
    assert response.status_code == 422


# Editing employees

def test_edits_only_the_fields_sent(client, base):
    created = _new_employee(client, base, target_hours=20, phone="077 123 4567")

    response = client.patch(base + f"/employees/{created['id']}", json={"max_hours": 35})
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["max_hours"] == 35
    assert edited["target_hours"] == 20
    assert edited["phone"] == "077 123 4567"
    assert edited["skills"] == ["server"]


def test_skills_are_replaced_and_null_clears_optional_fields(client, base):
    created = _new_employee(client, base, target_hours=20, phone="077 123 4567")

    edited = client.patch(
        base + f"/employees/{created['id']}",
        json={"skills": ["cook"], "target_hours": None, "phone": None},
    ).json()
    assert edited["skills"] == ["cook"]
    assert edited["target_hours"] is None
    assert edited["phone"] is None


def test_lowering_max_hours_below_the_target_is_invalid(client, base):
    created = _new_employee(client, base, target_hours=20)
    response = client.patch(base + f"/employees/{created['id']}", json={"max_hours": 10})
    assert response.status_code == 422
    assert client.get(base + f"/employees/{created['id']}").json()["max_hours"] == 30


@pytest.mark.parametrize("field", ["display_name", "max_hours", "skills", "status"])
def test_required_fields_cant_be_cleared(client, base, field):
    created = _new_employee(client, base)
    response = client.patch(base + f"/employees/{created['id']}", json={field: None})
    assert response.status_code == 422
    assert field in response.json()["detail"]["message"]


def test_unknown_fields_are_rejected(client, base):
    created = _new_employee(client, base)
    response = client.patch(base + f"/employees/{created['id']}", json={"maxhours": 10})
    assert response.status_code == 422


# Leaving and coming back

def test_inactive_staff_are_hidden_unless_asked_for(client, base):
    created = _new_employee(client, base)
    client.patch(base + f"/employees/{created['id']}", json={"status": "inactive"})

    active = [e["id"] for e in client.get(base + "/employees").json()]
    everyone = client.get(base + "/employees", params={"include_inactive": True}).json()
    assert created["id"] not in active
    assert any(e["id"] == created["id"] and e["status"] == "inactive" for e in everyone)

    client.patch(base + f"/employees/{created['id']}", json={"status": "active"})
    assert created["id"] in [e["id"] for e in client.get(base + "/employees").json()]


def test_new_drafts_leave_out_inactive_staff(client, base):
    staff = client.get(base + "/employees").json()
    leaver = staff[0]
    client.patch(base + f"/employees/{leaver['id']}", json={"status": "inactive"})

    draft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()["schedule"]
    assert leaver["id"] not in {a["employee_id"] for a in draft["assignments"]}


def _repair_after(client, base, candidates, change, undo) -> tuple:
    """Make `change` for each candidate until the week can be repaired."""
    for candidate in candidates:
        change(candidate)
        response = client.post(base + WEEK + "/repair", json={"deterministic": True})
        assert response.status_code == 200, response.text
        if response.json()["schedule"] is not None:
            return candidate, response.json()["schedule"]
        undo(candidate)  # this one leaves a gap nobody can fill; try another
    raise AssertionError("No repairable change found.")


def test_a_repair_takes_a_leaver_off_the_published_week(client, base):
    published = _published(client, base)
    people = sorted({a["employee_id"] for a in published["assignments"]})

    def leave(employee_id):
        client.patch(base + f"/employees/{employee_id}", json={"status": "inactive"})

    def come_back(employee_id):
        client.patch(base + f"/employees/{employee_id}", json={"status": "active"})

    leaver_id, repaired = _repair_after(client, base, people, leave, come_back)

    their_shifts = {a["shift_id"] for a in published["assignments"] if a["employee_id"] == leaver_id}
    assert leaver_id not in {a["employee_id"] for a in repaired["assignments"]}
    taken_off = {c["shift_id"] for c in repaired["changes"] if c["employee_id"] == leaver_id}
    assert taken_off == their_shifts


def test_a_repair_takes_someone_out_of_a_role_they_lost(client, base):
    published = _published(client, base)
    staff = {e["id"]: e for e in client.get(base + "/employees").json()}
    multi_role = [
        (staff[a["employee_id"]], a["role"])
        for a in published["assignments"]
        if len(staff[a["employee_id"]]["skills"]) > 1
    ]

    def drop_role(pair):
        person, role = pair
        kept = [skill for skill in person["skills"] if skill != role]
        client.patch(base + f"/employees/{person['id']}", json={"skills": kept})

    def give_back(pair):
        person, _ = pair
        client.patch(base + f"/employees/{person['id']}", json={"skills": person["skills"]})

    (person, role), repaired = _repair_after(client, base, multi_role, drop_role, give_back)
    assert (person["id"], role) not in {
        (a["employee_id"], a["role"]) for a in repaired["assignments"]
    }
