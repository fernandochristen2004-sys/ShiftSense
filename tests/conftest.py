"""Shared test fixtures.

Database tests use a separate database, shiftsense_test, so they never touch
your real data. Set SHIFTSENSE_TEST_DATABASE_URL to use a different one.
If the database isn't reachable, database tests are skipped with a reason.

Tests can run in parallel with `pytest -n auto` (pytest-xdist). Each worker
then gets its own copy, shiftsense_test_gw0, shiftsense_test_gw1, ..., made
on first use, because every run wipes and rebuilds its test database.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from db.session import CONNECT_ARGS

TEST_DATABASE_URL = os.environ.get(
    "SHIFTSENSE_TEST_DATABASE_URL",
    "postgresql+psycopg://shiftsense:shiftsense_dev@localhost:5432/shiftsense_test",
)
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _worker_database_url() -> str:
    """This worker's own test database: shiftsense_test_gw0 and so on.

    Without pytest-xdist (or with -n 0) it's the plain test database.
    The copy is created the first time, through the plain one.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return TEST_DATABASE_URL

    base = make_url(TEST_DATABASE_URL)
    url = base.set(database=f"{base.database}_{worker}")
    admin = create_engine(base, connect_args=CONNECT_ARGS, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.scalar(
                text("select 1 from pg_database where datname = :name"),
                {"name": url.database},
            )
            if not exists:
                try:
                    connection.execute(text(f'create database "{url.database}"'))
                except ProgrammingError:
                    pass  # another run made it at the same moment
    finally:
        admin.dispose()
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def db_engine():
    """A fresh test database, built by running every migration."""
    try:
        url = _worker_database_url()
        engine = create_engine(url, connect_args=CONNECT_ARGS)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except OperationalError:
        pytest.skip(
            "Test database not reachable. Start it with `docker compose up -d` "
            "and create it once with `docker exec shiftsense-db createdb -U "
            "shiftsense shiftsense_test`."
        )

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
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
