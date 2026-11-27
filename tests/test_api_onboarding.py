"""Tests for starting out: new restaurants, copying a week, and templates."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.deps import get_session
from api.main import app

MONDAY = "2026-11-23"
NEXT = "2026-11-30"
LATER = "2026-12-07"


@pytest.fixture
def client(db):
    def test_session():
        yield db

    app.dependency_overrides[get_session] = test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def demo(client) -> str:
    response = client.post("/restaurants/demo", params={"reset": True})  # a fresh one per test
    assert response.status_code == 200, response.text
    return f"/restaurants/{response.json()['id']}"


def _new(client, **fields) -> dict:
    body = {"name": "Lotus Kitchen", "timezone": "Asia/Colombo", "roles": ["cook", "server"]}
    response = client.post("/restaurants", json={**body, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def _plan(client, base, week) -> list[tuple]:
    """A week's shifts as (weekday date offset, times, label, needs), for comparing weeks."""
    shifts = client.get(base + f"/weeks/{week}/shifts").json()
    start = date.fromisoformat(week)
    return [
        (
            (date.fromisoformat(s["local_date"]) - start).days,
            s["local_start"],
            s["local_end"],
            s["label"],
            [(r["role"], r["count"], r["min_count"]) for r in s["requirements"]],
        )
        for s in shifts
    ]


def _code(response) -> str:
    return response.json()["detail"]["code"]


# New restaurants

def test_creates_an_empty_restaurant_with_its_roles(client):
    created = _new(client, name="  Lotus   Kitchen ", roles=["Cook", "server", "cook", " Host "])
    assert (created["name"], created["timezone"]) == ("Lotus Kitchen", "Asia/Colombo")
    base = f"/restaurants/{created['id']}"

    assert [s["name"] for s in client.get(base + "/skills").json()] == ["cook", "host", "server"]
    assert client.get(base + "/employees").json() == []
    assert client.get(base + f"/weeks/{MONDAY}/shifts").json() == []
    assert created["id"] in [r["id"] for r in client.get("/restaurants").json()]


@pytest.mark.parametrize(
    "fields, words",
    [
        ({"timezone": "Mars/Olympus"}, "Unknown timezone"),
        ({"name": "   "}, "name"),
        ({"roles": ["  "]}, "blank"),
    ],
)
def test_bad_restaurants_are_invalid(client, fields, words):
    response = client.post(
        "/restaurants", json={"name": "Lotus", "timezone": "Asia/Colombo", "roles": [], **fields},
    )
    assert response.status_code == 422
    assert words in response.json()["detail"]["message"]


def test_a_new_restaurant_can_be_scheduled_from_scratch(client):
    base = f"/restaurants/{_new(client)['id']}"
    noor = client.post(
        base + "/employees", json={"display_name": "Noor", "max_hours": 30, "skills": ["server"]},
    ).json()["id"]
    client.put(
        base + f"/employees/{noor}/availability/weekly",
        json={"rules": [{"weekday": 1, "start_time": "09:00", "end_time": "17:00"}]},
    )
    shift = client.post(base + "/shifts", json={
        "local_date": "2026-11-24", "start_time": "10:00", "end_time": "14:00",
        "requirements": [{"role": "server", "count": 1}],
    }).json()

    draft = client.post(base + f"/weeks/{MONDAY}/drafts", json={"deterministic": True}).json()
    assert draft["schedule"] is not None, draft
    assert [(a["shift_id"], a["employee_id"]) for a in draft["schedule"]["assignments"]] == [
        (shift["id"], noor),
    ]


def test_creates_a_demo_restaurant(client, demo):
    assert len(client.get(demo + "/employees").json()) == 25
    assert len(client.get(demo + f"/weeks/{MONDAY}/shifts").json()) > 0
    assert client.get(demo).json()["is_demo"] is True


def test_there_is_one_demo_until_it_is_reset(client):
    first = client.post("/restaurants/demo").json()
    assert client.post("/restaurants/demo").json()["id"] == first["id"]

    fresh = client.post("/restaurants/demo", params={"reset": True}).json()
    assert fresh["id"] != first["id"]
    assert client.post("/restaurants/demo").json()["id"] == fresh["id"]


def test_your_own_restaurant_is_not_a_demo(client):
    created = _new(client)
    assert created["is_demo"] is False
    listed = {r["id"]: r["is_demo"] for r in client.get("/restaurants").json()}
    assert listed[created["id"]] is False


# Copying a week

def test_copies_a_weeks_shifts_and_needs_into_an_empty_week(client, demo):
    response = client.post(demo + f"/weeks/{NEXT}/copy-shifts", json={"from_week": MONDAY})
    assert response.status_code == 201, response.text
    assert len(response.json()) == len(_plan(client, demo, MONDAY))
    assert _plan(client, demo, NEXT) == _plan(client, demo, MONDAY)


def test_copied_weeks_can_be_scheduled(client, demo):
    client.post(demo + f"/weeks/{NEXT}/copy-shifts", json={"from_week": MONDAY})
    draft = client.post(demo + f"/weeks/{NEXT}/drafts", json={"deterministic": True}).json()
    assert draft["schedule"] is not None, draft


def test_a_week_with_shifts_is_never_doubled(client, demo):
    client.post(demo + f"/weeks/{NEXT}/copy-shifts", json={"from_week": MONDAY})
    before = _plan(client, demo, NEXT)

    again = client.post(demo + f"/weeks/{NEXT}/copy-shifts", json={"from_week": MONDAY})
    assert again.status_code == 409
    assert _code(again) == "conflict"
    assert _plan(client, demo, NEXT) == before


def test_copying_an_empty_week_or_the_same_week_is_invalid(client, demo):
    empty = client.post(demo + f"/weeks/{LATER}/copy-shifts", json={"from_week": NEXT})
    assert empty.status_code == 422
    assert "no shifts to copy" in empty.json()["detail"]["message"]

    same = client.post(demo + f"/weeks/{MONDAY}/copy-shifts", json={"from_week": MONDAY})
    assert same.status_code == 422


def test_copying_keeps_local_times_across_a_clock_change(client):
    # The UK moves its clocks forward on Sunday 28 March 2027.
    base = f"/restaurants/{_new(client, timezone='Europe/London')['id']}"
    for day in ("2027-03-22", "2027-03-27"):
        client.post(base + "/shifts", json={
            "local_date": day, "start_time": "10:00", "end_time": "14:00",
            "requirements": [{"role": "cook", "count": 1}],
        })

    response = client.post(base + "/weeks/2027-03-29/copy-shifts", json={"from_week": "2027-03-22"})
    assert response.status_code == 201, response.text
    assert [(s["local_date"], s["local_start"]) for s in response.json()] == [
        ("2027-03-29", "10:00:00"),
        ("2027-04-03", "10:00:00"),
    ]


# Templates

def test_saves_lists_and_applies_a_template(client, demo):
    saved = client.post(demo + "/templates", json={"name": " Normal  week ", "week_start": MONDAY})
    assert saved.status_code == 201, saved.text
    template = saved.json()
    assert template["name"] == "Normal week"
    assert template["shift_count"] == len(_plan(client, demo, MONDAY))
    assert [t["id"] for t in client.get(demo + "/templates").json()] == [template["id"]]

    applied = client.post(demo + f"/weeks/{LATER}/apply-template", json={"template_id": template["id"]})
    assert applied.status_code == 201, applied.text
    assert _plan(client, demo, LATER) == _plan(client, demo, MONDAY)


def test_a_template_keeps_the_week_as_it_was_saved(client, demo):
    template = client.post(demo + "/templates", json={"name": "Normal", "week_start": MONDAY}).json()
    original = _plan(client, demo, MONDAY)
    first = client.get(demo + f"/weeks/{MONDAY}/shifts").json()[0]
    client.delete(demo + f"/shifts/{first['id']}")  # the source week changes afterwards

    client.post(demo + f"/weeks/{LATER}/apply-template", json={"template_id": template["id"]})
    assert _plan(client, demo, LATER) == original


def test_template_names_are_unique_and_need_shifts(client, demo):
    client.post(demo + "/templates", json={"name": "Normal", "week_start": MONDAY})
    duplicate = client.post(demo + "/templates", json={"name": "Normal", "week_start": MONDAY})
    assert duplicate.status_code == 409

    empty = client.post(demo + "/templates", json={"name": "Empty", "week_start": LATER})
    assert empty.status_code == 422
    assert "no shifts" in empty.json()["detail"]["message"]


def test_a_template_is_not_applied_over_existing_shifts(client, demo):
    template = client.post(demo + "/templates", json={"name": "Normal", "week_start": MONDAY}).json()
    response = client.post(demo + f"/weeks/{MONDAY}/apply-template", json={"template_id": template["id"]})
    assert response.status_code == 409


def test_deletes_a_template(client, demo):
    template = client.post(demo + "/templates", json={"name": "Normal", "week_start": MONDAY}).json()
    assert client.delete(demo + f"/templates/{template['id']}").status_code == 204
    assert client.get(demo + "/templates").json() == []

    gone = client.post(demo + f"/weeks/{LATER}/apply-template", json={"template_id": template["id"]})
    assert gone.status_code == 404


def test_another_restaurants_template_is_not_found(client, demo):
    template = client.post(demo + "/templates", json={"name": "Normal", "week_start": MONDAY}).json()
    other = f"/restaurants/{_new(client)['id']}"

    response = client.post(other + f"/weeks/{LATER}/apply-template", json={"template_id": template["id"]})
    assert response.status_code == 404
    assert client.delete(other + f"/templates/{template['id']}").status_code == 404
