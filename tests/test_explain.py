"""Explaining why a call-out can't be covered (optimizer/explain.py)."""

from datetime import datetime, timezone

from optimizer import engine
from optimizer.explain import explain_gaps, shift_label, summarize
from optimizer.models import DateTimeShift, Employee, SchedulingPolicy, ShiftRequirement

UTC = timezone.utc
WEEK = ((datetime(2026, 11, 23, tzinfo=UTC), datetime(2026, 11, 30, tzinfo=UTC)),)
SUNDAY_ONLY = ((datetime(2026, 11, 29, tzinfo=UTC), datetime(2026, 11, 30, tzinfo=UTC)),)


def _shift(shift_id, start_hour, end_hour, role="bartender"):
    return DateTimeShift(
        id=shift_id,
        starts_at=datetime(2026, 11, 28, start_hour, tzinfo=UTC),
        ends_at=datetime(2026, 11, 28, end_hour, tzinfo=UTC),
        requirements=(ShiftRequirement(role, 1),),
    )


BAR = _shift(1, 17, 23)
PATIO = _shift(2, 17, 23)
POLICY = SchedulingPolicy()


def _employee(employee_id, name, skills=("bartender",), max_hours=40, availability=WEEK):
    return Employee(
        id=employee_id,
        name=name,
        skills=frozenset(skills),
        max_hours=max_hours,
        datetime_availability=availability,
    )


OMAR = _employee(1, "Omar")
JADE = _employee(2, "Jade", availability=SUNDAY_ONLY)
THARINDU = _employee(3, "Tharindu")
RAVI = _employee(4, "Ravi", max_hours=4)
SAM = _employee(5, "Sam", skills=("cook",))
ORIGINAL = {1: {"bartender": [1]}, 2: {"bartender": [3]}}


def _gaps(employees, excluded=None, original=ORIGINAL):
    return explain_gaps(
        employees, [BAR, PATIO], POLICY, original, excluded or {1: [1]}, UTC,
    )


def test_each_qualified_person_gets_a_reason():
    [gap] = _gaps([OMAR, JADE, THARINDU, RAVI, SAM])

    assert (gap.shift_id, gap.role, gap.called_out) == (1, "bartender", (1,))
    reasons = {c.name: c.reason for c in gap.candidates}
    assert reasons == {
        "Jade": "not available",
        "Ravi": "would go over 4 h (already 0 h)",
        "Tharindu": "working Sat 28 17:00-23:00",
    }
    assert "Sam" not in reasons  # no bartender skill
    assert not gap.anyone_free


def test_summary_reads_like_a_sentence():
    employees = [OMAR, JADE, THARINDU, RAVI]
    text = summarize(_gaps(employees), UTC, [BAR, PATIO], {e.id: e.name for e in employees})

    assert text.startswith("Omar is off Sat 28 17:00-23:00 (bartender).")
    assert "Jade (not available)" in text
    assert "Tharindu (working Sat 28 17:00-23:00)" in text


def test_nobody_else_with_the_skill():
    text = summarize(_gaps([OMAR, SAM]), UTC, [BAR, PATIO], {1: "Omar", 5: "Sam"})
    assert "nobody else works bartender" in text


def test_a_free_person_is_reported_free():
    lena = _employee(6, "Lena")
    [gap] = _gaps([OMAR, JADE, lena])

    assert gap.anyone_free
    assert {c.name: c.reason for c in gap.candidates}["Lena"] is None


def test_explanation_agrees_with_the_solver():
    """When the explanation says nobody can fill the gap, the solver agrees.

    Like a real call-out, Omar is off every shift for the rest of the day.
    """
    employees = [OMAR, JADE, THARINDU, RAVI]
    rest_of_day = {1: [1], 2: [1]}
    [gap] = _gaps(employees, rest_of_day)
    result = engine.repair(
        employees=employees,
        shifts=[BAR, PATIO],
        policy=POLICY,
        original_schedule=ORIGINAL,
        excluded_assignments=rest_of_day,
        deterministic=True,
    )
    assert not gap.anyone_free
    assert result.assignments is None


def test_shift_label_uses_restaurant_time():
    from zoneinfo import ZoneInfo

    assert shift_label(BAR, ZoneInfo("Asia/Colombo")) == "Sat 28 22:30-04:30"
