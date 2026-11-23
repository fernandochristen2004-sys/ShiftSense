"""Database connection settings.

The database URL comes from the SHIFTSENSE_DATABASE_URL environment variable.
Without it, the local Docker database from docker-compose.yml is used.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

LOCAL_DATABASE_URL = (
    "postgresql+psycopg://shiftsense:shiftsense_dev@localhost:5432/shiftsense"
)


def database_url() -> str:
    return os.environ.get("SHIFTSENSE_DATABASE_URL", LOCAL_DATABASE_URL)


# Creating the engine does not connect yet; connections open when first used.
engine = create_engine(database_url())
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
