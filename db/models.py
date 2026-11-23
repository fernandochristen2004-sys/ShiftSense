"""SQLAlchemy models for the ShiftSense database.

These follow docs/schema.md. Every table belongs to a restaurant, and tables
that link two restaurant-owned records use composite foreign keys that
include restaurant_id, so the database itself prevents mixing restaurants.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    false,
    func,
    true,
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


# Availability

class AvailabilityRule(Base):
    """Recurring weekly availability (engine: WeeklyAvailability)."""

    __tablename__ = "availability_rules"

    id: Mapped[int] = _id()
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, comment="0 = Monday ... 6 = Sunday")
    start_time: Mapped[time] = mapped_column(Time, comment="Local wall-clock time")
    end_time: Mapped[time] = mapped_column(
        Time, comment="Earlier than start_time means the window crosses midnight"
    )

    __table_args__ = (
        CheckConstraint("weekday between 0 and 6", name="weekday_range"),
        CheckConstraint("start_time <> end_time", name="not_empty"),
        CheckConstraint(
            "extract(second from start_time) = 0 and extract(second from end_time) = 0",
            name="minute_precision",
        ),
    )


class AvailabilityException(Base):
    """A date that replaces the weekly availability (engine: AvailabilityException)."""

    __tablename__ = "availability_exceptions"

    id: Mapped[int] = _id()
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE")
    )
    local_date: Mapped[date] = mapped_column(Date, comment="Date in the restaurant's timezone")
    available: Mapped[bool] = mapped_column(
        Boolean, comment="false = off all day; true = only the listed intervals"
    )
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("employee_id", "local_date"),)


class AvailabilityExceptionInterval(Base):
    """A same-day time window for an 'available' exception."""

    __tablename__ = "availability_exception_intervals"

    id: Mapped[int] = _id()
    exception_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("availability_exceptions.id", ondelete="CASCADE"),
        index=True,
    )
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="same_day_order"),
        CheckConstraint(
            "extract(second from start_time) = 0 and extract(second from end_time) = 0",
            name="minute_precision",
        ),
    )


# Policy

class SchedulingPolicy(Base):
    """One row per restaurant (engine: SchedulingPolicy)."""

    __tablename__ = "scheduling_policies"

    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True
    )
    minimum_rest_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    enforce_minimum_rest: Mapped[bool] = mapped_column(Boolean, server_default=false())
    allow_split_shifts: Mapped[bool] = mapped_column(Boolean, server_default=false())
    split_shift_min_break_minutes: Mapped[int] = mapped_column(Integer, server_default="120")
    max_split_span_minutes: Mapped[int] = mapped_column(Integer, server_default="780")
    fairness_enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    allow_partial_coverage: Mapped[bool] = mapped_column(Boolean, server_default=false())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("minimum_rest_minutes >= 0", name="rest_non_negative"),
        # The engine still uses whole hours (see docs/limitations.md).
        CheckConstraint("mod(minimum_rest_minutes, 60) = 0", name="rest_whole_hours"),
        CheckConstraint("split_shift_min_break_minutes > 0", name="split_break_positive"),
        CheckConstraint(
            "max_split_span_minutes > split_shift_min_break_minutes",
            name="split_span_above_break",
        ),
        CheckConstraint(
            "not (allow_split_shifts and enforce_minimum_rest) "
            "or split_shift_min_break_minutes < minimum_rest_minutes",
            name="split_break_below_rest",
        ),
    )


# Demand

class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="RESTRICT")
    )
    label: Mapped[str | None] = mapped_column(Text, comment='e.g. "Friday dinner"')
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Text,
        server_default="active",
        comment="active / cancelled. Published shifts are replaced, not edited",
    )

    __table_args__ = (
        UniqueConstraint("restaurant_id", "id"),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        CheckConstraint("status in ('active', 'cancelled')", name="status"),
        CheckConstraint(
            "extract(second from starts_at) = 0 and extract(second from ends_at) = 0",
            name="minute_precision",
        ),
        Index("ix_shifts_restaurant_id_starts_at", "restaurant_id", "starts_at"),
    )


class ShiftRequirement(Base):
    """How many people a shift needs in one role (engine: ShiftRequirement)."""

    __tablename__ = "shift_requirements"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(BigInteger)
    shift_id: Mapped[int] = mapped_column(BigInteger)
    skill_id: Mapped[int] = mapped_column(BigInteger)
    count: Mapped[int] = mapped_column(Integer, comment="Target")
    min_count: Mapped[int] = mapped_column(
        Integer, comment="Equal to count when no shortfall is allowed"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "shift_id"],
            ["shifts.restaurant_id", "shifts.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "skill_id"],
            ["skills.restaurant_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("shift_id", "skill_id"),
        CheckConstraint("count >= 0", name="count_non_negative"),
        CheckConstraint("min_count between 0 and count", name="min_within_count"),
    )
