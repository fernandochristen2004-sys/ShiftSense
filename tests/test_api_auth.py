"""Tests for logging in and for who can see which restaurant.

These use the real login checks (REAL_AUTH), not the open access other
API tests run with.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.auth import COOKIE, login_attempts
from api.deps import get_session
from api.main import app
from db import models
from services.accounts import user_for_token

REAL_AUTH = True
PASSWORD = "correct horse battery"


@pytest.fixture
def browser(db):
    """A fresh browser: its own cookies, sharing the test database."""
    def test_session():
        yield db

    app.dependency_overrides[get_session] = test_session
    login_attempts._failures.clear()
    clients = []

    def new() -> TestClient:
        client = TestClient(app)
        clients.append(client)
        return client

    yield new
    app.dependency_overrides.clear()


def _sign_up(client, email="ana@example.com", password=PASSWORD) -> dict:
    response = client.post("/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


def _restaurant(client, name="Spice Garden") -> int:
    response = client.post(
        "/restaurants", json={"name": name, "timezone": "Asia/Colombo", "roles": ["cook"]},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _code(response) -> str:
    return response.json()["detail"]["code"]


# Not logged in

def test_everything_needs_a_login(browser):
    client = browser()
    for response in (
        client.get("/restaurants"),
        client.get("/restaurants/1/employees"),
        client.post("/restaurants/demo"),
        client.get("/auth/me"),
    ):
        assert response.status_code == 401
        assert _code(response) == "unauthorized"


def test_the_engine_endpoints_and_health_stay_open(browser):
    assert browser().get("/health").status_code == 200


# Signing up

def test_signing_up_logs_in(browser):
    client = browser()
    user = _sign_up(client, email="  Ana@Example.COM ")
    assert user["email"] == "ana@example.com"
    assert user["is_guest"] is False
    assert client.get("/auth/me").json() == user
    assert client.get("/restaurants").json() == []


def test_the_cookie_is_http_only_and_lax(browser):
    response = browser().post("/auth/signup", json={"email": "a@b.co", "password": PASSWORD})
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


@pytest.mark.parametrize(
    "email, password, words",
    [
        ("not-an-email", PASSWORD, "valid email"),
        ("ana@example.com", "short", "at least 8"),
    ],
)
def test_bad_signups_are_invalid(browser, email, password, words):
    response = browser().post("/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 422
    assert words in response.json()["detail"]["message"]


def test_an_email_can_only_sign_up_once(browser):
    _sign_up(browser())
    again = browser().post(
        "/auth/signup", json={"email": "ANA@example.com", "password": PASSWORD},
    )
    assert again.status_code == 409
    assert _code(again) == "conflict"


def test_passwords_and_tokens_are_never_stored_as_they_are(browser, db):
    client = browser()
    _sign_up(client)
    user = db.scalars(select(models.User).where(models.User.email == "ana@example.com")).one()
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2")

    token = client.cookies.get(COOKIE)
    stored = db.scalars(select(models.UserSession.token_hash)).all()
    assert token not in stored


# Logging in and out

def test_logging_in_and_out(browser):
    _sign_up(browser())
    client = browser()
    response = client.post("/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert response.status_code == 200
    assert client.get("/auth/me").json()["email"] == "ana@example.com"

    old_token = client.cookies.get(COOKIE)
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401

    client.cookies.set(COOKIE, old_token)  # the old cookie no longer works
    assert client.get("/auth/me").status_code == 401


def test_a_wrong_email_and_a_wrong_password_look_the_same(browser):
    _sign_up(browser())
    wrong_password = browser().post(
        "/auth/login", json={"email": "ana@example.com", "password": "nope-nope-nope"},
    )
    no_account = browser().post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD},
    )
    assert wrong_password.status_code == no_account.status_code == 401
    assert wrong_password.json() == no_account.json()


def test_too_many_wrong_passwords_are_slowed_down(browser):
    _sign_up(browser())
    client = browser()
    for _ in range(10):
        client.post("/auth/login", json={"email": "ana@example.com", "password": "wrong-password"})

    blocked = client.post("/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert blocked.status_code == 429
    assert _code(blocked) == "too_many_attempts"


def test_sessions_expire(browser, db):
    client = browser()
    _sign_up(client)
    token = client.cookies.get(COOKIE)
    assert user_for_token(db, token) is not None
    later = datetime.now(UTC) + timedelta(days=31)
    assert user_for_token(db, token, now=later) is None


# Who sees what

def test_each_account_sees_only_its_own_restaurants(browser):
    ana, ben = browser(), browser()
    _sign_up(ana, "ana@example.com")
    _sign_up(ben, "ben@example.com")
    anas = _restaurant(ana, "Ana's Café")

    assert [r["id"] for r in ana.get("/restaurants").json()] == [anas]
    assert ben.get("/restaurants").json() == []


def test_other_peoples_restaurants_look_like_they_dont_exist(browser):
    ana, ben = browser(), browser()
    _sign_up(ana, "ana@example.com")
    _sign_up(ben, "ben@example.com")
    anas = _restaurant(ana)

    for response in (
        ben.get(f"/restaurants/{anas}"),
        ben.get(f"/restaurants/{anas}/employees"),
        ben.post(f"/restaurants/{anas}/skills", json={"name": "spy"}),
        ben.get(f"/restaurants/{anas}/weeks/2026-11-23/shifts"),
    ):
        assert response.status_code == 404
        assert _code(response) == "not_found"

    assert ana.get(f"/restaurants/{anas}/employees").status_code == 200


def test_each_account_has_its_own_demo(browser):
    ana, ben = browser(), browser()
    _sign_up(ana, "ana@example.com")
    _sign_up(ben, "ben@example.com")

    anas_demo = ana.post("/restaurants/demo").json()["id"]
    bens_demo = ben.post("/restaurants/demo").json()["id"]
    assert anas_demo != bens_demo
    assert ana.post("/restaurants/demo").json()["id"] == anas_demo
    assert ben.get(f"/restaurants/{anas_demo}").status_code == 404


# Guests

def test_a_guest_can_try_the_demo(browser):
    guest = browser()
    response = guest.post("/auth/guest")
    assert response.status_code == 201
    assert response.json()["is_guest"] is True and response.json()["email"] is None

    demo = guest.post("/restaurants/demo").json()
    assert demo["is_demo"] is True
    assert len(guest.get(f"/restaurants/{demo['id']}/employees").json()) == 25


def test_a_guest_who_signs_up_keeps_their_work(browser):
    guest = browser()
    guest_id = guest.post("/auth/guest").json()["id"]
    demo = guest.post("/restaurants/demo").json()["id"]
    guest.post(f"/restaurants/{demo}/skills", json={"name": "barista"})

    user = _sign_up(guest, "ana@example.com")
    assert user["id"] == guest_id
    assert user["is_guest"] is False
    assert "barista" in [s["name"] for s in guest.get(f"/restaurants/{demo}/skills").json()]
