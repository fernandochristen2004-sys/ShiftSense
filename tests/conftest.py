"""Shared test fixtures.

Database tests use a separate database, shiftsense_test, so they never touch
your real data. Set SHIFTSENSE_TEST_DATABASE_URL to use a different one.
If the database isn't reachable, database tests are skipped with a reason.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from db.session import CONNECT_ARGS

TEST_DATABASE_URL = os.environ.get(
    "SHIFTSENSE_TEST_DATABASE_URL",
    "postgresql+psycopg://shiftsense:shiftsense_dev@localhost:5432/shiftsense_test",
)
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(scope="session")
def db_engine():
    """A fresh test database, built by running every migration."""
    engine = create_engine(TEST_DATABASE_URL, connect_args=CONNECT_ARGS)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except OperationalError:
        pytest.skip(
            "Test database not reachable. Start it with `docker compose up -d` "
            "and create it once with `docker exec shiftsense-db createdb -U "
            "shiftsense shiftsense_test`."
        )

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(config, "base")  # start clean, and prove downgrades work
    command.upgrade(config, "head")

    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    """A session whose changes are rolled back after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()
