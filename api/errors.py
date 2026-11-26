"""Structured API errors, shared by every router.

Errors come back as {"detail": {"code": ..., "message": ...}} so a
dashboard can react to the code:
    404 not_found               the restaurant, schedule, employee ... doesn't exist
    409 conflict                clashes with existing data (e.g. a duplicate name)
    409 stale                   someone changed the schedule; reload
    409 shortages_not_accepted  ask the manager to confirm, then resend
    422 invalid                 the request breaks a rule
"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from services.errors import ConflictError
from services.scheduling import ShortagesNotAcceptedError, StaleScheduleError


def error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@contextmanager
def service_errors() -> Iterator[None]:
    """Turn service exceptions into HTTP errors. Order matters: specific first."""
    try:
        yield
    except LookupError as exc:
        raise error(404, "not_found", str(exc)) from exc
    except ConflictError as exc:
        raise error(409, "conflict", str(exc)) from exc
    except ShortagesNotAcceptedError as exc:
        raise error(409, "shortages_not_accepted", str(exc)) from exc
    except StaleScheduleError as exc:
        raise error(409, "stale", str(exc)) from exc
    except (StaleDataError, IntegrityError) as exc:
        # Another request changed the same data at the same moment.
        raise error(
            409, "stale", "The data was changed by someone else. Reload and try again."
        ) from exc
    except ValueError as exc:
        raise error(422, "invalid", str(exc)) from exc
