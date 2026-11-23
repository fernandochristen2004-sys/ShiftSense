"""Tests for POST /schedules/repair."""

from fastapi.testclient import TestClient

from api.examples import scenario_request
from api.main import app
from optimizer.synthetic_data import generate_restaurant_scenario, pick_callout

client = TestClient(app)

URL = "/schedules/repair"
MONDAY = "2026-11-23"


def _employee(employee_id, name, start="09:00", end="23:30"):
    return {
        "id": employee_id,
        "name": name,
        "skills": ["server"],
        "max_hours": 40,
        "weekly_availability": [
            {"weekday": 0, "start_time": start, "end_time": end},
        ],
    }


def _shift(shift_id, start, end, count=1):
    return {
        "id": shift_id,
        "starts_at": f"{MONDAY}T{start}:00Z",
        "ends_at": f"{MONDAY}T{end}:00Z",
        "requirements": [{"skill": "server", "count": count}],
    }


def _request(**overrides) -> dict:
    """Asha works Monday lunch and dinner; Ben is free all day."""
    request = {
        "employees": [_employee(1, "Asha"), _employee(2, "Ben")],
        "shifts": [_shift(10, "11:00", "15:00"), _shift(11, "17:00", "23:00")],
        "policy": {"allow_split_shifts": True},
        "original_assignments": [
            {"shift_id": 10, "role": "server", "employee_id": 1},
            {"shift_id": 11, "role": "server", "employee_id": 1},
        ],
        "callouts": [{"shift_id": 10, "employee_id": 1}],
        "deterministic": True,
    }
    request.update(overrides)
    return request


def _assigned(body, shift_id):
    return sorted(
        a["employee_id"] for a in body["assignments"] if a["shift_id"] == shift_id
    )


# Successful repairs

def test_callout_is_covered_by_another_employee():
    response = client.post(URL, json=_request())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OPTIMAL"
    assert _assigned(body, 10) == [2]
    assert body["validation_errors"] == []


def test_callout_blocks_the_rest_of_the_day_by_default():
    body = client.post(URL, json=_request()).json()

    # Asha also loses dinner the same day; Ben covers both shifts.
    assert _assigned(body, 11) == [2]
    assert body["assignment_changes"] == 4


def test_callout_can_cover_only_one_shift():
    request = _request(callouts=[{"shift_id": 10, "employee_id": 1, "rest_of_day": False}])

    body = client.post(URL, json=request).json()

    assert _assigned(body, 10) == [2]
    assert _assigned(body, 11) == [1]
    assert body["assignment_changes"] == 2


def test_changes_list_who_left_and_who_joined():
    request = _request(callouts=[{"shift_id": 10, "employee_id": 1, "rest_of_day": False}])

    body = client.post(URL, json=request).json()

    assert body["changes"] == [
        {"shift_id": 10, "employee_id": 1, "before_role": "server", "after_role": None},
        {"shift_id": 10, "employee_id": 2, "before_role": None, "after_role": "server"},
    ]


def test_realistic_restaurant_callout_is_repaired():
    scenario = generate_restaurant_scenario(25, seed=42)
    generate_body = scenario_request(scenario, deterministic=True)
    original = client.post("/schedules/generate", json=generate_body).json()
    assert original["assignments"] is not None

    schedule = {}
    for a in original["assignments"]:
        schedule.setdefault(a["shift_id"], {}).setdefault(a["role"], []).append(a["employee_id"])

    for callout_seed in range(20):
        shift_id, employee_id = pick_callout(schedule, seed=callout_seed)
        request = {
            **generate_body,
            "original_assignments": original["assignments"],
            "callouts": [{"shift_id": shift_id, "employee_id": employee_id}],
        }
        body = client.post(URL, json=request).json()
        if body["assignments"] is not None:
            assert body["validation_errors"] == []
            assert employee_id not in _assigned(body, shift_id)
            assert body["assignment_changes"] == len(body["changes"])
            return

    raise AssertionError("No recoverable call-out found in 20 attempts.")


# Impossible repairs are results, not errors

def test_uncoverable_callout_returns_infeasible():
    # Only Asha can work; nobody can cover her.
    request = _request(employees=[_employee(1, "Asha"), _employee(2, "Ben", "20:00", "23:30")])

    response = client.post(URL, json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INFEASIBLE"
    assert body["assignments"] is None
    assert body["changes"] is None


# Invalid requests are rejected with 422

def test_callout_for_unknown_shift_is_rejected():
    request = _request(callouts=[{"shift_id": 99, "employee_id": 1}])

    response = client.post(URL, json=request)

    assert response.status_code == 422
    assert "unknown shift" in response.json()["detail"]


def test_callout_for_someone_not_on_the_shift_is_rejected():
    request = _request(callouts=[{"shift_id": 10, "employee_id": 2}])

    response = client.post(URL, json=request)

    assert response.status_code == 422
    assert "not scheduled" in response.json()["detail"]


def test_original_schedule_with_unknown_role_is_rejected():
    request = _request(
        original_assignments=[{"shift_id": 10, "role": "cook", "employee_id": 1}],
    )

    response = client.post(URL, json=request)

    assert response.status_code == 422
    assert "role" in response.json()["detail"]


def test_original_schedule_with_unknown_employee_is_rejected():
    request = _request(
        original_assignments=[
            {"shift_id": 10, "role": "server", "employee_id": 1},
            {"shift_id": 11, "role": "server", "employee_id": 99},
        ],
    )

    assert client.post(URL, json=request).status_code == 422


def test_repair_needs_at_least_one_callout():
    assert client.post(URL, json=_request(callouts=[])).status_code == 422
