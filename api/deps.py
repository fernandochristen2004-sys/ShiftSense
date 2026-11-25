"""Shared request dependencies."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from db.session import SessionLocal


def get_session() -> Iterator[Session]:
    """One database session per request.

    Endpoints commit when their work succeeds. Anything not committed is
    rolled back when the session closes, so a failed request saves nothing.
    Tests replace this dependency with a session that is rolled back.
    """
    with SessionLocal() as session:
        yield session
