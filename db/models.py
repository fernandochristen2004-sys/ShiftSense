"""SQLAlchemy models for the ShiftSense database.

These follow docs/schema.md. Every table belongs to a restaurant, and tables
that link two restaurant-owned records use composite foreign keys that
include restaurant_id, so the database itself prevents mixing restaurants.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names make migrations and error messages readable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _id() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = _id()
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, comment="IANA name, e.g. Asia/Colombo")
    created_at: Mapped[datetime] = _created_at()


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="RESTRICT")
    )
    employee_number: Mapped[str | None] = mapped_column(
        Text, comment="Payroll/POS number. Unique per restaurant when present"
    )
    display_name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    max_minutes: Mapped[int] = mapped_column(Integer)
    target_minutes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("restaurant_id", "id"),
        UniqueConstraint("restaurant_id", "employee_number"),
        CheckConstraint("status in ('active', 'inactive')", name="status"),
        CheckConstraint("max_minutes >= 0", name="max_minutes_non_negative"),
        # The engine still uses whole hours (see docs/limitations.md).
        CheckConstraint("mod(max_minutes, 60) = 0", name="max_minutes_whole_hours"),
        CheckConstraint(
            "target_minutes is null or target_minutes between 0 and max_minutes",
            name="target_within_max",
        ),
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_not_blank"),
    )


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(Text, comment="cook, server, ...")

    __table_args__ = (
        UniqueConstraint("restaurant_id", "id"),
        UniqueConstraint("restaurant_id", "name"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
    )


class EmployeeSkill(Base):
    __tablename__ = "employee_skills"

    restaurant_id: Mapped[int] = mapped_column(BigInteger)
    employee_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    skill_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "employee_id"],
            ["employees.restaurant_id", "employees.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "skill_id"],
            ["skills.restaurant_id", "skills.id"],
            ondelete="RESTRICT",
        ),
    )
