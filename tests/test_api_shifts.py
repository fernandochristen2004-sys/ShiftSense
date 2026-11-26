"""Tests for managing shifts: add, edit, remove."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from api.deps import get_session
from api.main import app
from services.demo import seed_demo_restaurant

MONDAY = date(2026, 11, 23)
WEEK = f"/weeks/{MONDAY.isoformat()}"
BREAKFAST = {
    "local_date": "2026-11-24",
    "start_time": "07:00",
    "end_time": "11:00",
    "label": "  Breakfast ",
    "requirements": [{"role": "cook", "count": 1}, {"role": "server", "count": 2, "min_count": 1}],
}


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


def _add(client, base, **changes) -> dict:
    response = client.post(base + "/shifts", json={**BREAKFAST, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def _week_ids(client, base) -> list[int]:
    return [s["id"] for s in client.get(base + WEEK + "/shifts").json()]


def _code(response) -> str:
    return response.json()["detail"]["code"]


def _publish_draft(client, base) -> dict:
    draft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()["schedule"]
    response = client.post(
        base + f"/schedules/{draft['id']}/publish",
        json={"expected_row_version": draft["row_version"], "accept_shortages": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _covered_or_short(schedule, shift_id) -> bool:
    return any(a["shift_id"] == shift_id for a in schedule["assignments"]) or any(
        s["shift_id"] == shift_id for s in schedule["shortages"]
    )


# Adding

def test_adds_a_breakfast_shift_in_restaurant_time(client, base):
    shift = _add(client, base)
    assert shift["label"] == "Breakfast"
    assert (shift["local_date"], shift["local_start"], shift["local_end"]) == (
        "2026-11-24", "07:00:00", "11:00:00",
    )
    assert shift["requirements"] == [
        {"role": "cook", "count": 1, "min_count": 1},
        {"role": "server", "count": 2, "min_count": 1},
    ]
    starts = datetime.fromisoformat(shift["starts_at"])
    assert (datetime.fromisoformat(shift["ends_at"]) - starts).total_seconds() == 4 * 3600

    week = client.get(base + WEEK + "/shifts").json()
    tuesday = [s for s in week if s["local_date"] == "2026-11-24"]
    assert tuesday[0]["id"] == shift["id"]  # earliest that day


def test_an_earlier_end_means_the_next_day(client, base):
    shift = _add(client, base, start_time="23:00", end_time="02:00")
    starts = datetime.fromisoformat(shift["starts_at"])
    ends = datetime.fromisoformat(shift["ends_at"])
    assert (ends - starts).total_seconds() == 3 * 3600
    assert shift["local_end"] == "02:00:00"


@pytest.mark.parametrize(
    "changes, words",
    [
        ({"start_time": "07:00", "end_time": "07:00"}, "same time"),
        ({"start_time": "06:00", "end_time": "05:00"}, "at most 16 hours"),
        ({"start_time": "07:00:30"}, "whole minutes"),
        ({"requirements": [{"role": "juggler", "count": 1}]}, "juggler"),
        ({"requirements": [{"role": "cook", "count": 1}, {"role": "COOK", "count": 2}]}, "only once"),
        ({"requirements": [{"role": "cook", "count": 1, "min_count": 2}]}, "between 0 and 1"),
    ],
)
def test_bad_shifts_are_invalid_and_nothing_is_saved(client, base, changes, words):
    before = _week_ids(client, base)
    response = client.post(base + "/shifts", json={**BREAKFAST, **changes})
    assert response.status_code == 422
    assert words in response.json()["detail"]["message"]
    assert _week_ids(client, base) == before


@pytest.mark.parametrize("requirements", [[], [{"role": "cook", "count": 0}]])
def test_a_shift_needs_people(client, base, requirements):
    response = client.post(base + "/shifts", json={**BREAKFAST, "requirements": requirements})
    assert response.status_code == 422


OPTIONAL = [{"role": "cook", "count": 1, "min_count": 0}, {"role": "server", "count": 1, "min_count": 0}]


def test_new_shifts_go_into_new_drafts(client, base):
    shift = _add(client, base, requirements=OPTIONAL)
    draft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()["schedule"]
    assert _covered_or_short(draft, shift["id"])


def test_a_shift_added_after_publishing_is_filled_by_a_repair(client, base):
    _publish_draft(client, base)
    shift = _add(client, base, requirements=OPTIONAL)

    repair = client.post(base + WEEK + "/repair", json={"deterministic": True}).json()
    assert repair["schedule"] is not None, repair
    assert _covered_or_short(repair["schedule"], shift["id"])


def test_a_required_shift_nobody_can_work_makes_the_week_infeasible(client, base):
    # Nobody in the demo is available before 10:00, so a required 07:00 cook
    # can't be found. The engine says so instead of quietly skipping the shift.
    _add(client, base)
    draft = client.post(base + WEEK + "/drafts", json={"deterministic": True}).json()
    assert draft["status"] == "INFEASIBLE"
    assert draft["schedule"] is None


# Editing

def test_edits_a_shift_nobody_has_seen(client, base):
    shift = _add(client, base)
    response = client.patch(
        base + f"/shifts/{shift['id']}",
        json={"start_time": "06:30", "label": None, "requirements": [{"role": "cook", "count": 2}]},
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert (edited["local_start"], edited["local_end"]) == ("06:30:00", "11:00:00")
    assert edited["label"] is None
    assert edited["requirements"] == [{"role": "cook", "count": 2, "min_count": 2}]


def test_moving_a_shift_to_another_day_keeps_its_times(client, base):
    shift = _add(client, base)
    edited = client.patch(base + f"/shifts/{shift['id']}", json={"local_date": "2026-11-25"}).json()
    assert (edited["local_date"], edited["local_start"], edited["local_end"]) == (
        "2026-11-25", "07:00:00", "11:00:00",
    )


def test_a_bad_edit_changes_nothing(client, base):
    shift = _add(client, base)
    response = client.patch(base + f"/shifts/{shift['id']}", json={"end_time": "07:00"})
    assert response.status_code == 422
    week = {s["id"]: s for s in client.get(base + WEEK + "/shifts").json()}
    assert week[shift["id"]]["local_end"] == "11:00:00"


@pytest.mark.parametrize("field", ["local_date", "start_time", "end_time", "requirements"])
def test_required_fields_cant_be_cleared(client, base, field):
    shift = _add(client, base)
    response = client.patch(base + f"/shifts/{shift['id']}", json={field: None})
    assert response.status_code == 422
    assert field in response.json()["detail"]["message"]


def test_a_published_shift_keeps_its_times_and_staffing(client, base):
    published = _publish_draft(client, base)
    shift_id = published["assignments"][0]["shift_id"]

    for change in ({"start_time": "10:00"}, {"requirements": [{"role": "cook", "count": 9}]}):
        response = client.patch(base + f"/shifts/{shift_id}", json=change)
        assert response.status_code == 409
        assert _code(response) == "conflict"

    renamed = client.patch(base + f"/shifts/{shift_id}", json={"label": "Chef's table"})
    assert renamed.status_code == 200
    assert renamed.json()["label"] == "Chef's table"


def test_another_restaurants_shift_is_not_found(client, base, db):
    other = seed_demo_restaurant(db, employee_count=8)
    outsider = client.get(f"/restaurants/{other.restaurant_id}{WEEK}/shifts").json()[0]["id"]

    assert client.patch(base + f"/shifts/{outsider}", json={"label": "x"}).status_code == 404
    assert client.delete(base + f"/shifts/{outsider}").status_code == 404


# Removing

def test_removes_an_unused_shift(client, base):
    shift = _add(client, base)
    assert client.delete(base + f"/shifts/{shift['id']}").status_code == 204
    assert shift["id"] not in _week_ids(client, base)

    again = client.delete(base + f"/shifts/{shift['id']}")
    assert again.status_code == 404
    assert _code(again) == "not_found"


def test_cancelling_a_published_shift_and_repairing_takes_its_staff_off(client, base):
    published = _publish_draft(client, base)
    on_it: dict[int, set[int]] = {}
    for a in published["assignments"]:
        on_it.setdefault(a["shift_id"], set()).add(a["employee_id"])

    for shift_id, staff in on_it.items():
        assert client.delete(base + f"/shifts/{shift_id}").status_code == 204
        assert shift_id not in _week_ids(client, base)

        repair = client.post(base + WEEK + "/repair", json={"deterministic": True}).json()
        if repair["schedule"] is None:
            continue  # an earlier call-out or rule blocks this week; try the next shift
        schedule = repair["schedule"]
        assert shift_id not in {a["shift_id"] for a in schedule["assignments"]}
        taken_off = {c["employee_id"] for c in schedule["changes"] if c["shift_id"] == shift_id}
        assert taken_off == staff

        callout = client.post(
            base + "/callouts", json={"shift_id": shift_id, "employee_id": next(iter(staff))},
        )
        assert callout.status_code == 422
        assert "cancelled" in callout.json()["detail"]["message"]
        return
    raise AssertionError("No repairable cancellation found.")
