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

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Badly formed requests get the same {code, message} shape as every other error.

    FastAPI's default is a list of raw validation details, which a dashboard
    can't show to a person. This keeps the first problem, in words.
    """
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = first.get("msg", "Invalid request.")
    if where:
        message = f"{where}: {message}"
    return JSONResponse(status_code=422, content={"detail": {"code": "invalid", "message": message}})
