"""Logging in, and checking who can see which restaurant.

The browser holds a random session token in an HttpOnly cookie, which page
scripts can't read. Every /restaurants/... endpoint needs a logged-in user
who is a member of that restaurant; for anyone else it answers 404, so other
people's restaurants can't even be detected.

Set SHIFTSENSE_SECURE_COOKIES=true when serving over HTTPS.
"""

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import Field
from sqlalchemy.orm import Session

from api.deps import get_session
from api.errors import error, service_errors
from api.schemas import ApiModel
from db import models as db
from services.accounts import (
    SESSION_DAYS,
    create_guest,
    end_session,
    log_in,
    restaurant_ids,
    sign_up,
    start_session,
    user_for_token,
)
from services.cleanup import clean_up_guests

COOKIE = "shiftsense_session"
SECURE_COOKIES = os.environ.get("SHIFTSENSE_SECURE_COOKIES", "false").lower() == "true"


# Who's asking, and what they may see

@dataclass(frozen=True)
class Access:
    """The logged-in user and their restaurants. restaurant_ids None = every restaurant
    (only for tests and admin scripts, which replace get_access)."""

    user_id: int | None
    restaurant_ids: frozenset[int] | None

    def allows(self, restaurant_id: int) -> bool:
        return self.restaurant_ids is None or restaurant_id in self.restaurant_ids


def get_current_user(request: Request, session: Session = Depends(get_session)) -> db.User | None:
    return user_for_token(session, request.cookies.get(COOKIE))


def get_access(
    user: db.User | None = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Access:
    if user is None:
        raise error(401, "unauthorized", "Log in to continue.")
    return Access(user_id=user.id, restaurant_ids=restaurant_ids(session, user.id))


def require_restaurant_access(request: Request, access: Access = Depends(get_access)) -> None:
    """For every /restaurants/{restaurant_id}/... route: members only, 404 for others."""
    raw = request.path_params.get("restaurant_id")
    if raw is None:
        return
    restaurant_id = int(raw)
    if not access.allows(restaurant_id):
        raise error(404, "not_found", f"Restaurant {restaurant_id} not found.")


# Too many wrong passwords

class AttemptLimiter:
    """At most `limit` failed logins per email in `window` seconds.

    Kept in memory, so it resets when the API restarts and isn't shared
    between several API servers; enough for one server.
    """

    def __init__(self, limit: int = 10, window: float = 15 * 60):
        self.limit, self.window = limit, window
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        with self._lock:
            failures = self._prune(key)
            return len(failures) >= self.limit

    def failed(self, key: str) -> None:
        with self._lock:
            self._prune(key).append(time.monotonic())

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _prune(self, key: str) -> deque[float]:
        failures = self._failures[key]
        while failures and failures[0] < time.monotonic() - self.window:
            failures.popleft()
        return failures


login_attempts = AttemptLimiter()


# Endpoints

class Credentials(ApiModel):
    email: str = Field(max_length=254, examples=["christen@example.com"])
    password: str = Field(max_length=128)


class UserOut(ApiModel):
    id: int
    email: str | None
    is_guest: bool


router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: db.User) -> UserOut:
    return UserOut(id=user.id, email=user.email, is_guest=user.is_guest)


def _log_in_browser(response: Response, session: Session, user: db.User) -> None:
    token = start_session(session, user)
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,  # page scripts can't read it
        secure=SECURE_COOKIES,  # HTTPS only, when deployed
        samesite="lax",  # not sent with requests from other sites
        path="/",
    )


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(
    request: Credentials,
    response: Response,
    session: Session = Depends(get_session),
    current: db.User | None = Depends(get_current_user),
) -> UserOut:
    """Create an account and log in. A guest who signs up keeps what they made."""
    with service_errors():
        user = sign_up(session, request.email, request.password, guest=current)
        _log_in_browser(response, session, user)
        session.commit()
        return _user_out(user)


@router.post("/login", response_model=UserOut)
def login(
    request: Credentials, response: Response, session: Session = Depends(get_session)
) -> UserOut:
    """Log in. A wrong email and a wrong password get the same answer."""
    key = request.email.strip().lower()
    if login_attempts.blocked(key):
        raise error(429, "too_many_attempts", "Too many tries. Wait 15 minutes, then try again.")
    with service_errors():
        try:
            user = log_in(session, request.email, request.password)
        except Exception:
            login_attempts.failed(key)
            raise
        login_attempts.succeeded(key)
        _log_in_browser(response, session, user)
        session.commit()
        return _user_out(user)


@router.post("/guest", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def guest(response: Response, session: Session = Depends(get_session)) -> UserOut:
    """Try ShiftSense without an account. Sign up later to keep what you made.

    Each new guest also clears out a few guests older than a week, so demos
    don't pile up without needing a scheduled job.
    """
    clean_up_guests(session)
    user = create_guest(session)
    _log_in_browser(response, session, user)
    session.commit()
    return _user_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, session: Session = Depends(get_session)
) -> Response:
    end_session(session, request.cookies.get(COOKIE))
    session.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=SECURE_COOKIES, samesite="lax")
    return response


@router.get("/me", response_model=UserOut)
def me(user: db.User | None = Depends(get_current_user)) -> UserOut:
    """Who's logged in, or 401."""
    if user is None:
        raise error(401, "unauthorized", "Log in to continue.")
    return _user_out(user)
