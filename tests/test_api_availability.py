"""Tests for availability: weekly hours and date exceptions."""

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


@pytest.fixture
def noor(client, base) -> int:
    """A new employee with no availability yet."""
    response = client.post(
        base + "/employees", json={"display_name": "Noor", "max_hours": 30, "skills": ["server"]},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _url(base, employee_id, rest="") -> str:
    return base + f"/employees/{employee_id}/availability" + rest


def _code(response) -> str:
    return response.json()["detail"]["code"]


def _shift_days(client, base) -> dict[int, str]:
    """shift id -> the date it starts, restaurant time."""
    return {s["id"]: s["local_date"] for s in client.get(base + WEEK + "/shifts").json()}


# Reading

def test_a_new_employee_has_no_availability(client, base, noor):
    availability = client.get(_url(base, noor)).json()
    assert availability == {"employee_id": noor, "weekly": [], "exceptions": []}


def test_reads_a_seeded_employees_weekly_hours(client, base):
    someone = client.get(base + "/employees").json()[0]
    weekly = client.get(_url(base, someone["id"])).json()["weekly"]
    assert weekly
    assert weekly == sorted(weekly, key=lambda r: (r["weekday"], r["start_time"]))


def test_another_restaurants_employee_is_not_found(client, base, db):
    other = seed_demo_restaurant(db, employee_count=8)
    outsider = client.get(f"/restaurants/{other.restaurant_id}/employees").json()[0]["id"]

    assert client.get(_url(base, outsider)).status_code == 404
    response = client.put(_url(base, outsider, "/weekly"), json={"rules": []})
    assert response.status_code == 404
    response = client.put(_url(base, outsider, "/exceptions/2026-12-01"), json={"available": False})
    assert response.status_code == 404


# Weekly hours

def test_replaces_weekly_hours_sorted_and_without_repeats(client, base, noor):
    rules = [
        {"weekday": 4, "start_time": "16:00", "end_time": "02:00"},  # crosses midnight
        {"weekday": 0, "start_time": "10:00", "end_time": "23:00"},
        {"weekday": 0, "start_time": "10:00", "end_time": "23:00"},
    ]
    response = client.put(_url(base, noor, "/weekly"), json={"rules": rules})
    assert response.status_code == 200, response.text
    assert response.json()["weekly"] == [
        {"weekday": 0, "start_time": "10:00:00", "end_time": "23:00:00"},
        {"weekday": 4, "start_time": "16:00:00", "end_time": "02:00:00"},
    ]

    replaced = client.put(
        _url(base, noor, "/weekly"),
        json={"rules": [{"weekday": 6, "start_time": "09:00", "end_time": "15:00"}]},
    ).json()
    assert [r["weekday"] for r in replaced["weekly"]] == [6]


@pytest.mark.parametrize(
    "rule",
    [
        {"weekday": 7, "start_time": "10:00", "end_time": "12:00"},  # no such weekday
        {"weekday": 0, "start_time": "10:00", "end_time": "10:00"},  # empty
        {"weekday": 0, "start_time": "10:00:30", "end_time": "12:00"},  # seconds
        {"weekday": 0, "start_time": "10:00"},  # missing end
    ],
)
def test_bad_weekly_rules_are_invalid_and_change_nothing(client, base, noor, rule):
    good = {"weekday": 1, "start_time": "10:00", "end_time": "18:00"}
    client.put(_url(base, noor, "/weekly"), json={"rules": [good]})

    response = client.put(_url(base, noor, "/weekly"), json={"rules": [good, rule]})
    assert response.status_code == 422
    assert len(client.get(_url(base, noor)).json()["weekly"]) == 1


def test_weekly_hours_keep_date_exceptions(client, base, noor):
    client.put(_url(base, noor, "/exceptions/2026-12-01"), json={"available": False})
    client.put(_url(base, noor, "/weekly"), json={"rules": []})
    assert len(client.get(_url(base, noor)).json()["exceptions"]) == 1


# Date exceptions

def test_sets_a_day_off(client, base, noor):
    response = client.put(
        _url(base, noor, "/exceptions/2026-12-01"), json={"available": False, "note": " Exam "},
    )
    assert response.status_code == 200, response.text
    assert response.json()["exceptions"] == [
        {"date": "2026-12-01", "available": False, "intervals": [], "note": "Exam"},
    ]


def test_sets_a_partly_available_day_and_replaces_it(client, base, noor):
    url = _url(base, noor, "/exceptions/2026-12-02")
    client.put(url, json={
        "available": True,
        "intervals": [
            {"start_time": "17:00", "end_time": "23:00"},
            {"start_time": "09:00", "end_time": "12:00"},
        ],
    })
    first = client.get(_url(base, noor)).json()["exceptions"][0]
    assert [i["start_time"] for i in first["intervals"]] == ["09:00:00", "17:00:00"]

    client.put(url, json={"available": False})
    exceptions = client.get(_url(base, noor)).json()["exceptions"]
    assert exceptions == [{"date": "2026-12-02", "available": False, "intervals": [], "note": None}]


@pytest.mark.parametrize(
    "body",
    [
        {"available": True},  # available, but no windows
        {"available": False, "intervals": [{"start_time": "09:00", "end_time": "12:00"}]},
        {"available": True, "intervals": [{"start_time": "12:00", "end_time": "09:00"}]},
        {"available": True, "intervals": [{"start_time": "22:00", "end_time": "02:00"}]},
    ],
)
def test_bad_exceptions_are_invalid_and_change_nothing(client, base, noor, body):
    url = _url(base, noor, "/exceptions/2026-12-03")
    client.put(url, json={"available": False, "note": "keep me"})

    response = client.put(url, json=body)
    assert response.status_code == 422
    assert _code(response) == "invalid"
    assert client.get(_url(base, noor)).json()["exceptions"][0]["note"] == "keep me"


def test_removes_an_exception(client, base, noor):
    url = _url(base, noor, "/exceptions/2026-12-01")
    client.put(url, json={"available": False})

    assert client.delete(url).status_code == 204
    assert client.get(_url(base, noor)).json()["exceptions"] == []

    again = client.delete(url)
    assert again.status_code == 404
    assert _code(again) == "not_found"


# The schedule follows availability

def test_new_staff_can_be_scheduled_once_they_have_hours(client, base, noor):
    def drafted_with_noor() -> bool:
        draft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()
        return noor in {a["employee_id"] for a in draft["schedule"]["assignments"]}

    assert not drafted_with_noor()  # no hours: never available

    # 06:00 to 05:59 the next morning: every shift, all week.
    every_day = [{"weekday": d, "start_time": "06:00", "end_time": "05:59"} for d in range(7)]
    client.put(_url(base, noor, "/weekly"), json={"rules": every_day})
    client.patch(base + f"/employees/{noor}", json={"target_hours": 30})
    assert drafted_with_noor()


def test_a_day_off_keeps_someone_off_that_days_shifts(client, base, demo):
    draft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()["schedule"]
    days = _shift_days(client, base)

    first = draft["assignments"][0]
    day = days[first["shift_id"]]
    client.put(_url(base, first["employee_id"], f"/exceptions/{day}"), json={"available": False})

    redraft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()["schedule"]
    their_days = {
        days[a["shift_id"]]
        for a in redraft["assignments"]
        if a["employee_id"] == first["employee_id"]
    }
    assert day not in their_days


def test_a_repair_moves_someone_off_a_day_they_can_no_longer_work(client, base):
    draft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()["schedule"]
    published = client.post(
        base + f"/schedules/{draft['id']}/publish",
        json={"expected_row_version": draft["row_version"], "accept_shortages": True},
    ).json()
    days = _shift_days(client, base)

    for assignment in published["assignments"]:
        person = assignment["employee_id"]
        day = days[assignment["shift_id"]]
        url = _url(base, person, f"/exceptions/{day}")
        client.put(url, json={"available": False})

        repair = client.post(base + WEEK + "/repair", json={"deterministic": True}).json()
        if repair["schedule"] is None:
            client.delete(url)  # nobody can cover this one; try another day off
            continue

        on_that_day = {
            a["shift_id"]
            for a in repair["schedule"]["assignments"]
            if a["employee_id"] == person
            and days[a["shift_id"]] == day
        }
        assert on_that_day == set()
        assert any(
            c["employee_id"] == person and c["shift_id"] == assignment["shift_id"]
            for c in repair["schedule"]["changes"]
        )
        return
    raise AssertionError("No repairable day off found.")
