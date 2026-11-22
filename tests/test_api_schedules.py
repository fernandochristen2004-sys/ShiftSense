"""Tests for POST /schedules/generate."""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from optimizer.synthetic_data import generate_restaurant_scenario

client = TestClient(app)

URL = "/schedules/generate"


def _small_request(**overrides) -> dict:
    """Two servers, one lunch shift needing one server."""
    request = {
        "employees": [
            {
                "id": 1,
                "name": "Asha",
                "skills": ["server"],
                "max_hours": 20,
                "weekly_availability": [
                    {"weekday": 0, "start_time": "09:00", "end_time": "17:00"},
                ],
            },
            {
                "id": 2,
                "name": "Ben",
                "skills": ["server"],
                "max_hours": 20,
                "weekly_availability": [
                    {"weekday": 0, "start_time": "09:00", "end_time": "17:00"},
                ],
            },
        ],
        "shifts": [
            {
                "id": 10,
                "starts_at": "2026-11-23T11:00:00Z",  # a Monday
                "ends_at": "2026-11-23T15:00:00Z",
                "requirements": [{"skill": "server", "count": 1}],
            },
        ],
    }
    request.update(overrides)
    return request


def _scenario_request(scenario, deterministic: bool = False) -> dict:
    """Convert a synthetic restaurant into the API's JSON format."""
    policy = scenario.policy
    return {
        "employees": [
            {
                "id": e.id,
                "name": e.name,
                "skills": sorted(e.skills),
                "max_hours": e.max_hours,
                "target_minutes": e.target_minutes,
                "datetime_availability": [
                    {"starts_at": start.isoformat(), "ends_at": end.isoformat()}
                    for start, end in e.datetime_availability
                ],
            }
            for e in scenario.employees
        ],
        "shifts": [
            {
                "id": s.id,
                "starts_at": s.starts_at.isoformat(),
                "ends_at": s.ends_at.isoformat(),
                "requirements": [
                    {"skill": r.skill, "count": r.count, "min_count": r.min_count}
                    for r in s.requirements
                ],
            }
            for s in scenario.shifts
        ],
        "policy": {
            "minimum_rest_hours": policy.minimum_rest_hours,
            "enforce_minimum_rest": policy.enforce_minimum_rest,
            "fairness_enabled": policy.fairness_enabled,
            "allow_split_shifts": policy.allow_split_shifts,
            "split_shift_min_break_minutes": policy.split_shift_min_break_minutes,
            "max_split_span_minutes": policy.max_split_span_minutes,
            "allow_partial_coverage": policy.allow_partial_coverage,
        },
        "deterministic": deterministic,
    }


# Successful generation

def test_small_schedule_is_generated():
    response = client.post(URL, json=_small_request())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OPTIMAL"
    assert len(body["assignments"]) == 1
    assert body["assignments"][0]["shift_id"] == 10
    assert body["assignments"][0]["role"] == "server"
    assert body["assignments"][0]["employee_id"] in (1, 2)
    assert body["fully_covered"] is True
    assert body["shortages"] == []
    assert body["validation_errors"] == []


def test_realistic_restaurant_is_generated():
    scenario = generate_restaurant_scenario(25, seed=42)

    response = client.post(URL, json=_scenario_request(scenario))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("OPTIMAL", "FEASIBLE")
    assert body["validation_errors"] == []
    assert body["fully_covered"] == (body["shortages"] == [])

    shift_ids = {s.id for s in scenario.shifts}
    employee_ids = {e.id for e in scenario.employees}
    for assignment in body["assignments"]:
        assert assignment["shift_id"] in shift_ids
        assert assignment["employee_id"] in employee_ids


def test_deterministic_requests_return_the_same_schedule():
    scenario = generate_restaurant_scenario(25, seed=42)
    request = _scenario_request(scenario, deterministic=True)

    first = client.post(URL, json=request).json()
    second = client.post(URL, json=request).json()

    assert first["assignments"] == second["assignments"]


def test_locked_assignment_is_kept():
    request = _small_request(
        locked_assignments=[{"shift_id": 10, "role": "server", "employee_id": 2}],
    )

    body = client.post(URL, json=request).json()

    assert body["assignments"] == [{"shift_id": 10, "role": "server", "employee_id": 2}]


def test_excluded_employee_is_not_assigned():
    request = _small_request(
        excluded_assignments=[{"shift_id": 10, "employee_id": 1}],
    )

    body = client.post(URL, json=request).json()

    assert body["assignments"] == [{"shift_id": 10, "role": "server", "employee_id": 2}]


def test_timezone_is_used_for_weekly_availability():
    # 11:00–15:00 UTC is 16:30–20:30 in Colombo, outside 09:00–17:00 local.
    request = _small_request(timezone="Asia/Colombo")

    body = client.post(URL, json=request).json()

    assert body["status"] == "INFEASIBLE"


# Impossible schedules are results, not errors

def test_impossible_schedule_returns_infeasible_not_an_error():
    request = _small_request()
    request["shifts"][0]["requirements"] = [{"skill": "server", "count": 3}]

    response = client.post(URL, json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INFEASIBLE"
    assert body["assignments"] is None
    assert body["fully_covered"] is None


# Invalid input is rejected with 422

def test_missing_required_field_is_rejected():
    request = _small_request()
    del request["employees"][0]["max_hours"]

    assert client.post(URL, json=request).status_code == 422


def test_unknown_field_is_rejected():
    request = _small_request()
    request["employees"][0]["maxhours"] = 20

    assert client.post(URL, json=request).status_code == 422


def test_time_without_timezone_is_rejected():
    request = _small_request()
    request["shifts"][0]["starts_at"] = "2026-11-23T11:00:00"

    assert client.post(URL, json=request).status_code == 422


def test_shift_ending_before_it_starts_is_rejected_with_a_message():
    request = _small_request()
    request["shifts"][0]["ends_at"] = "2026-11-23T10:00:00Z"

    response = client.post(URL, json=request)

    assert response.status_code == 422
    assert "after" in response.json()["detail"].lower()


def test_unknown_timezone_is_rejected():
    response = client.post(URL, json=_small_request(timezone="Mars/Olympus"))

    assert response.status_code == 422
    assert "timezone" in response.json()["detail"].lower()


@pytest.mark.parametrize("field, value", [("max_hours", -1), ("id", 0)])
def test_out_of_range_numbers_are_rejected(field, value):
    request = _small_request()
    request["employees"][0][field] = value

    assert client.post(URL, json=request).status_code == 422
