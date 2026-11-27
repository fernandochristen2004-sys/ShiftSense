"""Accounts: signing up, logging in, sessions and who can see which restaurant.

Passwords are hashed with Argon2 and never stored or logged. A session is a
random token in an HttpOnly cookie; the database keeps only its SHA-256, so a
leaked database can't be used to log in.

Like the other services, these never commit.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db import models as db
from services.errors import ConflictError

SESSION_DAYS = 30
MIN_PASSWORD = 8
MAX_PASSWORD = 128
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_hasher = PasswordHasher()
# Checked when an email has no account, so a wrong email takes as long as a
# wrong password and doesn't reveal which emails are registered.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


class AuthError(Exception):
    """Wrong email or password, or not logged in."""


# Signing up and logging in

def sign_up(
    session: Session, email: str, password: str, guest: db.User | None = None
) -> db.User:
    """A new account. A guest who signs up keeps everything they made."""
    email = _clean_email(email)
    _check_password(password)
    if session.scalar(select(db.User.id).where(db.User.email == email)):
        raise ConflictError("There's already an account with that email. Log in instead.")

    user = guest if guest is not None and guest.is_guest else db.User()
    user.email = email
    user.password_hash = _hasher.hash(password)
    user.is_guest = False
    session.add(user)
    session.flush()
    return user


def log_in(session: Session, email: str, password: str) -> db.User:
    user = session.scalars(
        select(db.User).where(db.User.email == email.strip().lower())
    ).first()
    try:
        _hasher.verify(user.password_hash if user else _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        raise AuthError("Wrong email or password.") from None
    if user is None:
        raise AuthError("Wrong email or password.")

    if _hasher.check_needs_rehash(user.password_hash):  # stronger settings since signup
        user.password_hash = _hasher.hash(password)
    return user


def create_guest(session: Session) -> db.User:
    """Someone trying ShiftSense without an account."""
    guest = db.User(is_guest=True)
    session.add(guest)
    session.flush()
    return guest


def _clean_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL.match(email) or len(email) > 254:
        raise ValueError("Enter a valid email address, like name@example.com.")
    return email


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Use at least {MIN_PASSWORD} characters for your password.")
    if len(password) > MAX_PASSWORD:
        raise ValueError(f"Use at most {MAX_PASSWORD} characters for your password.")


# Sessions

def start_session(session: Session, user: db.User, now: datetime | None = None) -> str:
    """Log a browser in. Returns the token for its cookie (shown only once)."""
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    session.add(db.UserSession(
        token_hash=_digest(token),
        user_id=user.id,
        expires_at=now + timedelta(days=SESSION_DAYS),
    ))
    session.flush()
    return token


def user_for_token(session: Session, token: str | None, now: datetime | None = None):
    """The logged-in user for a cookie token, or None (missing, unknown or expired)."""
    if not token:
        return None
    row = session.scalars(
        select(db.UserSession).where(db.UserSession.token_hash == _digest(token))
    ).first()
    if row is None or row.expires_at <= (now or datetime.now(UTC)):
        return None
    return session.get(db.User, row.user_id)


def end_session(session: Session, token: str | None) -> None:
    """Log a browser out. Unknown tokens are ignored."""
    if token:
        session.execute(delete(db.UserSession).where(db.UserSession.token_hash == _digest(token)))
        session.flush()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Who can see which restaurant

def add_member(session: Session, user_id: int, restaurant_id: int, role: str = "owner") -> None:
    session.add(db.Membership(user_id=user_id, restaurant_id=restaurant_id, role=role))
    session.flush()


def restaurant_ids(session: Session, user_id: int) -> frozenset[int]:
    return frozenset(session.scalars(
        select(db.Membership.restaurant_id).where(db.Membership.user_id == user_id)
    ))
