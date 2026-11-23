"""Check that Python can reach the ShiftSense database."""

from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg://shiftsense:shiftsense_dev@localhost:5432/shiftsense"


def main() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        database, version = connection.execute(
            text("select current_database(), version()")
        ).one()
    print(f"Connected to database '{database}'")
    print(version)


if __name__ == "__main__":
    main()