"""Database connection settings.

The database URL comes from the SHIFTSENSE_DATABASE_URL environment variable,
as a host gives it (postgres://... is fine). Without it, the local Docker
database from docker-compose.yml is used.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

LOCAL_DATABASE_URL = (
    "postgresql+psycopg://shiftsense:shiftsense_dev@localhost:5432/shiftsense"
)


def database_url() -> str:
    return normalize_url(os.environ.get("SHIFTSENSE_DATABASE_URL", LOCAL_DATABASE_URL))


def normalize_url(url: str) -> str:
    """Use the psycopg 3 driver whatever scheme a host hands out.

    Neon, Render and others give postgres:// or postgresql:// URLs, which
    SQLAlchemy would read as the older psycopg2 driver.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


# Every connection works in UTC, so times come back the same way whatever the
# database server's own timezone setting is. Local times are worked out from
# the restaurant's timezone in Python, never by the database.
CONNECT_ARGS = {"options": "-c timezone=UTC"}

# Creating the engine does not connect yet; connections open when first used.
engine = create_engine(database_url(), connect_args=CONNECT_ARGS)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
