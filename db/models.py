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
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    is_demo: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), comment="Sample data to try the app with"
    )
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


# Results

class Schedule(Base):
    """One revision of a restaurant's staffing for a planning period."""

    __tablename__ = "schedules"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="RESTRICT")
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision_number: Mapped[int] = mapped_column(
        Integer, comment="1, 2, 3 ... per restaurant and period. Shown to managers"
    )
    based_on_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="The revision this one was repaired or edited from"
    )
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    row_version: Mapped[int] = mapped_column(
        Integer, comment="Optimistic concurrency: stale updates are rejected"
    )
    solver_status: Mapped[str | None] = mapped_column(Text)
    fully_covered: Mapped[bool | None] = mapped_column(Boolean)
    shortages: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    objective_values: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    schedule_metrics: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    assignment_changes: Mapped[int | None] = mapped_column(Integer, comment="Repairs only")
    created_at: Mapped[datetime] = _created_at()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # SQLAlchemy checks and increments row_version on every update.
    __mapper_args__ = {"version_id_col": row_version}

    __table_args__ = (
        UniqueConstraint("restaurant_id", "id"),
        UniqueConstraint("restaurant_id", "period_start", "revision_number"),
        ForeignKeyConstraint(
            ["restaurant_id", "based_on_id"],
            ["schedules.restaurant_id", "schedules.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("period_end > period_start", name="period_order"),
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        CheckConstraint("status in ('draft', 'published', 'archived')", name="status"),
        CheckConstraint(
            "assignment_changes is null or assignment_changes >= 0",
            name="changes_non_negative",
        ),
        CheckConstraint(
            "status <> 'published' or published_at is not null",
            name="published_has_time",
        ),
        CheckConstraint(
            "jsonb_typeof(shortages) = 'array'", name="shortages_is_array"
        ),
        # At most one published revision per restaurant and period.
        Index(
            "uq_schedules_one_published_per_period",
            "restaurant_id",
            "period_start",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )


class Assignment(Base):
    """One employee working one shift in one role, within a schedule revision."""

    __tablename__ = "assignments"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(BigInteger)
    schedule_id: Mapped[int] = mapped_column(BigInteger, index=True)
    shift_id: Mapped[int] = mapped_column(BigInteger)
    employee_id: Mapped[int] = mapped_column(BigInteger)
    skill_id: Mapped[int] = mapped_column(BigInteger, comment="The role worked")

    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "schedule_id"],
            ["schedules.restaurant_id", "schedules.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "shift_id"],
            ["shifts.restaurant_id", "shifts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "employee_id"],
            ["employees.restaurant_id", "employees.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "skill_id"],
            ["skills.restaurant_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        # One role per person per shift, enforced by the database too.
        UniqueConstraint("schedule_id", "shift_id", "employee_id"),
    )


class Lock(Base):
    """A manager's decision the solver must respect in a draft schedule."""

    __tablename__ = "locks"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(BigInteger)
    schedule_id: Mapped[int] = mapped_column(BigInteger, index=True)
    shift_id: Mapped[int] = mapped_column(BigInteger)
    employee_id: Mapped[int] = mapped_column(BigInteger)
    skill_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Required for must_work, empty for must_not_work"
    )
    kind: Mapped[str] = mapped_column(Text, comment="must_work / must_not_work")

    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "schedule_id"],
            ["schedules.restaurant_id", "schedules.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "shift_id"],
            ["shifts.restaurant_id", "shifts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "employee_id"],
            ["employees.restaurant_id", "employees.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "skill_id"],
            ["skills.restaurant_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        # A lock can't say both "must work" and "must not work".
        UniqueConstraint("schedule_id", "shift_id", "employee_id"),
        CheckConstraint(
            "(kind = 'must_work' and skill_id is not null) "
            "or (kind = 'must_not_work' and skill_id is null)",
            name="kind_matches_skill",
        ),
    )


class Absence(Base):
    """A call-out. Loaded into repairs as 'must not work' exclusions."""

    __tablename__ = "absences"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(BigInteger)
    employee_id: Mapped[int] = mapped_column(BigInteger)
    shift_id: Mapped[int] = mapped_column(BigInteger)
    rest_of_day: Mapped[bool] = mapped_column(
        Boolean,
        server_default=true(),
        comment="Also off until 06:00 the next morning (restaurant time)",
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        ForeignKeyConstraint(
            ["restaurant_id", "employee_id"],
            ["employees.restaurant_id", "employees.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["restaurant_id", "shift_id"],
            ["shifts.restaurant_id", "shifts.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("employee_id", "shift_id"),
    )


class ShiftTemplate(Base):
    """A saved week of shift needs, to start a new week from.

    `shifts` is a list of {"weekday": 0-6, "start_time": "HH:MM", "end_time": "HH:MM",
    "label": str | null, "requirements": [{"role": str, "count": int, "min_count": int}]},
    in restaurant time. Roles are stored by name and checked when the template is used.
    """

    __tablename__ = "shift_templates"

    id: Mapped[int] = _id()
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    shifts: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (UniqueConstraint("restaurant_id", "name"),)
