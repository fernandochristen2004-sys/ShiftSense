"""Tests for the stored-data endpoints: draft → publish → call-out → repair."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.deps import get_session
from api.main import app
from db import models
from optimizer.synthetic_data import pick_callout
from services.demo import seed_demo_restaurant

MONDAY = date(2026, 11, 23)
WEEK = f"/weeks/{MONDAY.isoformat()}"


@pytest.fixture
def client(db):
    """A test client whose requests use the rolled-back test session."""
    def test_session():
        yield db

    app.dependency_overrides[get_session] = test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def demo(db):
    return seed_demo_restaurant(db, employee_count=25)


def _base(demo) -> str:
    return f"/restaurants/{demo.restaurant_id}"


def _draft(client, demo) -> dict:
    response = client.post(_base(demo) + WEEK + "/drafts", json={"deterministic": True})
    assert response.status_code == 200, response.text
    return response.json()["schedule"]


def _publish(client, demo, schedule) -> dict:
    response = client.post(
        _base(demo) + f"/schedules/{schedule['id']}/publish",
        json={"expected_row_version": schedule["row_version"], "accept_shortages": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _engine_format(schedule) -> dict:
    result: dict = {}
    for a in schedule["assignments"]:
        result.setdefault(a["shift_id"], {}).setdefault(a["role"], []).append(a["employee_id"])
    return result


def _repair_after_callout(client, db, demo, published) -> tuple[dict, dict]:
    """Record call-outs until one can be repaired; return (callout, repair)."""
    for callout_seed in range(20):
        shift_id, employee_id = pick_callout(_engine_format(published), seed=callout_seed)
        callout = client.post(
            _base(demo) + "/callouts",
            json={"shift_id": shift_id, "employee_id": employee_id, "note": "sick"},
        )
        assert callout.status_code == 201, callout.text
        repair = client.post(_base(demo) + WEEK + "/repair", json={"deterministic": True})
        assert repair.status_code == 200, repair.text
        if repair.json()["schedule"] is not None:
            return callout.json(), repair.json()
        # Not repairable: remove this call-out and try another one.
        db.delete(db.get(models.Absence, callout.json()["id"]))
        db.flush()
    raise AssertionError("No repairable call-out found in 20 attempts.")


# Drafts

def test_generating_a_draft(client, demo):
    response = client.post(_base(demo) + WEEK + "/drafts", json={"deterministic": True})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("OPTIMAL", "FEASIBLE")
    schedule = body["schedule"]
    assert schedule["status"] == "draft"
    assert schedule["revision_number"] == 1
    assert schedule["based_on_id"] is None
    assert schedule["changes"] is None
    assert schedule["assignments"]
    assert all(a["employee_name"] for a in schedule["assignments"])


def test_draft_body_is_optional(client, demo):
    response = client.post(_base(demo) + WEEK + "/drafts")
    assert response.status_code == 200
    assert response.json()["schedule"] is not None


def test_second_draft_is_revision_two(client, demo):
    _draft(client, demo)
    assert _draft(client, demo)["revision_number"] == 2


def test_week_must_start_on_monday(client, demo):
    response = client.post(_base(demo) + "/weeks/2026-11-24/drafts")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid"


def test_unknown_restaurant_is_404(client):
    response = client.post("/restaurants/999999" + WEEK + "/drafts")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_unknown_fields_are_rejected(client, demo):
    response = client.post(_base(demo) + WEEK + "/drafts", json={"determinstic": True})
    assert response.status_code == 422


def test_week_without_staff_returns_422(client, db, demo):
    db.query(models.Employee).filter_by(restaurant_id=demo.restaurant_id).update(
        {"status": "inactive"}
    )
    response = client.post(_base(demo) + WEEK + "/drafts")
    assert response.status_code == 422


# Viewing

def test_listing_revisions_newest_first(client, demo):
    _draft(client, demo)
    _draft(client, demo)

    response = client.get(_base(demo) + WEEK + "/schedules")

    assert response.status_code == 200
    assert [s["revision_number"] for s in response.json()] == [2, 1]


def test_listing_an_empty_week(client, demo):
    response = client.get(_base(demo) + "/weeks/2026-11-30/schedules")
    assert response.status_code == 200
    assert response.json() == []


def test_getting_one_schedule(client, demo):
    draft = _draft(client, demo)

    response = client.get(_base(demo) + f"/schedules/{draft['id']}")

    assert response.status_code == 200
    assert response.json() == draft


def test_schedules_are_private_to_their_restaurant(client, db, demo):
    draft = _draft(client, demo)
    other = seed_demo_restaurant(db, employee_count=10, name="Other Bistro")

    response = client.get(f"/restaurants/{other.restaurant_id}/schedules/{draft['id']}")
    assert response.status_code == 404

    response = client.post(
        f"/restaurants/{other.restaurant_id}/schedules/{draft['id']}/publish",
        json={"expected_row_version": draft["row_version"], "accept_shortages": True},
    )
    assert response.status_code == 404


def test_published_schedule_of_a_week(client, demo):
    assert client.get(_base(demo) + WEEK + "/published").status_code == 404

    published = _publish(client, demo, _draft(client, demo))

    response = client.get(_base(demo) + WEEK + "/published")
    assert response.status_code == 200
    assert response.json() == published


# Publishing

def test_publishing_a_draft(client, demo):
    draft = _draft(client, demo)

    published = _publish(client, demo, draft)

    assert published["status"] == "published"
    assert published["published_at"] is not None
    assert published["row_version"] == draft["row_version"] + 1


def test_shortages_need_confirmation(client, demo):
    draft = _draft(client, demo)
    assert draft["shortages"], "the demo week is a few positions short"

    response = client.post(
        _base(demo) + f"/schedules/{draft['id']}/publish",
        json={"expected_row_version": draft["row_version"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "shortages_not_accepted"


def test_stale_version_is_409(client, demo):
    draft = _draft(client, demo)

    response = client.post(
        _base(demo) + f"/schedules/{draft['id']}/publish",
        json={"expected_row_version": draft["row_version"] + 5, "accept_shortages": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale"


def test_publishing_twice_is_refused(client, demo):
    draft = _draft(client, demo)
    published = _publish(client, demo, draft)

    response = client.post(
        _base(demo) + f"/schedules/{draft['id']}/publish",
        json={"expected_row_version": published["row_version"], "accept_shortages": True},
    )

    assert response.status_code == 422


def test_publishing_a_new_draft_archives_the_old_one(client, demo):
    first = _publish(client, demo, _draft(client, demo))
    second = _publish(client, demo, _draft(client, demo))

    statuses = {
        s["id"]: s["status"]
        for s in client.get(_base(demo) + WEEK + "/schedules").json()
    }
    assert statuses == {first["id"]: "archived", second["id"]: "published"}


# Call-outs

def test_recording_and_listing_callouts(client, demo):
    published = _publish(client, demo, _draft(client, demo))
    shift_id, employee_id = pick_callout(_engine_format(published), seed=0)

    response = client.post(
        _base(demo) + "/callouts",
        json={"shift_id": shift_id, "employee_id": employee_id, "note": "sick"},
    )

    assert response.status_code == 201
    callout = response.json()
    assert callout["rest_of_day"] is True
    assert callout["note"] == "sick"
    assert callout["reported_at"]
    assert client.get(_base(demo) + WEEK + "/callouts").json() == [callout]


def test_callout_twice_is_refused(client, demo):
    published = _publish(client, demo, _draft(client, demo))
    shift_id, employee_id = pick_callout(_engine_format(published), seed=0)
    body = {"shift_id": shift_id, "employee_id": employee_id}

    assert client.post(_base(demo) + "/callouts", json=body).status_code == 201
    response = client.post(_base(demo) + "/callouts", json=body)

    assert response.status_code == 422
    assert "already recorded" in response.json()["detail"]["message"]


def test_callout_needs_a_published_schedule(client, demo):
    draft = _draft(client, demo)
    shift_id, employee_id = pick_callout(_engine_format(draft), seed=0)

    response = client.post(
        _base(demo) + "/callouts", json={"shift_id": shift_id, "employee_id": employee_id},
    )

    assert response.status_code == 422


def test_callout_for_unknown_shift_is_404(client, demo):
    _publish(client, demo, _draft(client, demo))
    response = client.post(
        _base(demo) + "/callouts", json={"shift_id": 999999, "employee_id": 1},
    )
    assert response.status_code == 404


# Repairs

def test_repair_needs_a_published_schedule(client, demo):
    _draft(client, demo)
    response = client.post(_base(demo) + WEEK + "/repair")
    assert response.status_code == 404


def test_full_flow(client, db, demo):
    """Draft → publish → call-out → repair → publish the repair."""
    published = _publish(client, demo, _draft(client, demo))
    callout, repair = _repair_after_callout(client, db, demo, published)

    schedule = repair["schedule"]
    assert schedule["status"] == "draft"
    assert schedule["based_on_id"] == published["id"]
    assert schedule["revision_number"] == 2

    # The called-out person is off that shift, and the change is listed.
    on_shift = [
        a["employee_id"] for a in schedule["assignments"]
        if a["shift_id"] == callout["shift_id"]
    ]
    assert callout["employee_id"] not in on_shift
    change = next(
        c for c in schedule["changes"]
        if c["shift_id"] == callout["shift_id"] and c["employee_id"] == callout["employee_id"]
    )
    assert change["before_role"] is not None
    assert change["after_role"] is None

    # The original stays published until the repair is approved.
    assert client.get(_base(demo) + f"/schedules/{published['id']}").json()["status"] == "published"

    final = _publish(client, demo, schedule)
    assert final["status"] == "published"
    assert client.get(_base(demo) + f"/schedules/{published['id']}").json()["status"] == "archived"


def test_outdated_repair_is_refused(client, db, demo):
    """Two repairs from the same revision: once one is published, the other is stale."""
    published = _publish(client, demo, _draft(client, demo))
    _, first = _repair_after_callout(client, db, demo, published)
    second = client.post(_base(demo) + WEEK + "/repair", json={"deterministic": True}).json()

    _publish(client, demo, first["schedule"])
    response = client.post(
        _base(demo) + f"/schedules/{second['schedule']['id']}/publish",
        json={
            "expected_row_version": second["schedule"]["row_version"],
            "accept_shortages": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale"


# Restaurant and week data

def test_listing_restaurants(client, demo):
    response = client.get("/restaurants")
    assert response.status_code == 200
    assert {"id": demo.restaurant_id, "name": "Demo Bistro", "timezone": "UTC"} in response.json()


def test_getting_a_restaurant(client, demo):
    response = client.get(_base(demo))
    assert response.status_code == 200
    assert response.json() == {"id": demo.restaurant_id, "name": "Demo Bistro", "timezone": "UTC"}


def test_unknown_restaurant_details_are_404(client):
    assert client.get("/restaurants/999999").status_code == 404


def test_listing_shifts(client, demo):
    response = client.get(_base(demo) + WEEK + "/shifts")

    assert response.status_code == 200
    shifts = response.json()
    assert {s["id"] for s in shifts} == set(demo.shift_ids.values())
    assert shifts == sorted(shifts, key=lambda s: s["starts_at"])
    first = shifts[0]
    assert first["local_date"] == "2026-11-23"
    assert first["local_start"] == "11:00:00"
    assert first["requirements"]
    assert all(r["min_count"] <= r["count"] for s in shifts for r in s["requirements"])


def test_late_shift_ends_after_midnight(client, demo):
    shifts = client.get(_base(demo) + WEEK + "/shifts").json()
    late = [s for s in shifts if s["local_start"] == "23:00:00"]
    assert late, "the demo week has Friday and Saturday late closes"
    assert all(s["local_end"] < s["local_start"] for s in late)


def test_shift_times_use_the_restaurant_timezone(client, db, demo):
    db.get(models.Restaurant, demo.restaurant_id).timezone = "Asia/Colombo"
    db.flush()

    # Monday 11:00 UTC is 16:30 in Colombo. Monday 00:00 Colombo is still in the week.
    shifts = client.get(_base(demo) + WEEK + "/shifts").json()

    assert shifts[0]["local_start"] == "16:30:00"


def test_dashboard_origin_is_allowed(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "PUT", "DELETE"])
def test_dashboard_can_use_every_method_the_api_has(client, method):
    response = client.options(
        "/restaurants/1/callouts/1",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method},
    )
    assert response.status_code == 200
    assert method in response.headers["access-control-allow-methods"]


def test_other_origins_are_not_allowed(client):
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_demo_staff_have_friendly_names(client, demo):
    names = {a["employee_name"] for a in _draft(client, demo)["assignments"]}
    assert "Asha" in names or "Ben" in names
    assert not any(name.startswith("Employee ") for name in names)


# Call-out risk

def test_risk_needs_a_published_schedule(client, demo):
    _draft(client, demo)
    response = client.get(_base(demo) + WEEK + "/risk")
    assert response.status_code == 404


def test_risk_report(client, demo):
    published = _publish(client, demo, _draft(client, demo))

    response = client.get(_base(demo) + WEEK + "/risk")

    assert response.status_code == 200
    body = response.json()
    assert body["schedule_id"] == published["id"]
    assert body["checked"] == len(published["assignments"]) == len(body["risks"])
    assert body["at_risk"] == sum(r["level"] != "covered" for r in body["risks"])
    assert all(r["employee_name"] for r in body["risks"])


# Cancelling call-outs and explaining failed repairs

def test_cancelling_a_callout(client, demo):
    published = _publish(client, demo, _draft(client, demo))
    shift_id, employee_id = pick_callout(_engine_format(published), seed=0)
    callout = client.post(
        _base(demo) + "/callouts", json={"shift_id": shift_id, "employee_id": employee_id},
    ).json()

    response = client.delete(_base(demo) + f"/callouts/{callout['id']}")

    assert response.status_code == 204
    assert client.get(_base(demo) + WEEK + "/callouts").json() == []
    assert client.delete(_base(demo) + f"/callouts/{callout['id']}").status_code == 404


def test_callouts_are_private_to_their_restaurant(client, db, demo):
    published = _publish(client, demo, _draft(client, demo))
    shift_id, employee_id = pick_callout(_engine_format(published), seed=0)
    callout = client.post(
        _base(demo) + "/callouts", json={"shift_id": shift_id, "employee_id": employee_id},
    ).json()
    other = seed_demo_restaurant(db, employee_count=10, name="Other Bistro")

    response = client.delete(f"/restaurants/{other.restaurant_id}/callouts/{callout['id']}")

    assert response.status_code == 404


def test_failed_repair_explains_why(client, demo):
    _publish(client, demo, _draft(client, demo))
    risks = client.get(_base(demo) + WEEK + "/risk").json()["risks"]
    no_fix = next(r for r in risks if r["level"] == "no_fix")
    client.post(
        _base(demo) + "/callouts",
        json={"shift_id": no_fix["shift_id"], "employee_id": no_fix["employee_id"]},
    )

    body = client.post(_base(demo) + WEEK + "/repair", json={"deterministic": True}).json()

    assert body["schedule"] is None
    assert body["explanation"] == no_fix["why"]
    assert no_fix["employee_name"] in body["explanation"]["summary"]
    gap = body["explanation"]["gaps"][0]
    assert gap["called_out"][0]["name"] == no_fix["employee_name"]
    assert gap["candidates"]
    assert all(c["reason"] != "called_out" for c in gap["candidates"])


# Ranked replacements

def _covered_callout_with_options(client, demo):
    """Record a call-out that has more than one way to cover it."""
    _publish(client, demo, _draft(client, demo))
    risks = client.get(_base(demo) + WEEK + "/risk").json()["risks"]
    for risk in (r for r in risks if r["level"] == "covered"):
        body = {"shift_id": risk["shift_id"], "employee_id": risk["employee_id"]}
        callout = client.post(_base(demo) + "/callouts", json=body).json()
        options = client.post(_base(demo) + WEEK + "/repair-options", json=body).json()
        if len(options["options"]) > 1:
            return risk, options
        client.delete(_base(demo) + f"/callouts/{callout['id']}")
    pytest.skip("no call-out with several options in this demo week")


def test_repair_options(client, demo):
    risk, options = _covered_callout_with_options(client, demo)

    assert options["shift_id"] == risk["shift_id"]
    assert options["role"] == risk["role"]
    assert options["why"] is None
    best = options["options"][0]
    assert best["cover"]["name"]
    assert best["extra_missing"] == 0
    assert best["changes"] == risk["changes"]
    assert any(
        c["employee_id"] == risk["employee_id"] and c["after_role"] is None
        for c in best["change_list"]
    )
    assert any(
        a["employee_id"] == best["cover"]["employee_id"] and a["shift_id"] == risk["shift_id"]
        for a in best["assignments"]
    )


def test_saving_a_chosen_option(client, demo):
    risk, options = _covered_callout_with_options(client, demo)
    chosen = options["options"][1]

    response = client.post(
        _base(demo) + WEEK + "/repair",
        json={
            "deterministic": True,
            "cover": {
                "shift_id": risk["shift_id"],
                "role": risk["role"],
                "employee_id": chosen["cover"]["employee_id"],
            },
        },
    )

    assert response.status_code == 200
    saved = response.json()["schedule"]
    as_set = lambda items: {(a["shift_id"], a["role"], a["employee_id"]) for a in items}
    assert as_set(saved["assignments"]) == as_set(chosen["assignments"])
    assert saved["assignment_changes"] == chosen["changes"]


def test_options_need_a_recorded_callout(client, demo):
    published = _publish(client, demo, _draft(client, demo))
    shift_id, employee_id = pick_callout(_engine_format(published), seed=0)

    response = client.post(
        _base(demo) + WEEK + "/repair-options",
        json={"shift_id": shift_id, "employee_id": employee_id},
    )

    assert response.status_code == 422
    assert "Record the call-out first" in response.json()["detail"]["message"]
