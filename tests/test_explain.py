"""Explaining why a call-out can't be covered (optimizer/explain.py)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from optimizer import engine
from optimizer.explain import explain_gaps, reason_text, shift_label, summarize
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
SHIFTS = [BAR, PATIO]
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


def _explain(employees, excluded=None):
    return explain_gaps(employees, SHIFTS, POLICY, ORIGINAL, excluded or {1: [1]}, UTC)


def test_each_qualified_person_gets_a_reason():
    explanation = _explain([OMAR, JADE, THARINDU, RAVI, SAM])
    [gap] = explanation.gaps

    assert (gap.shift_id, gap.role, gap.called_out) == (1, "bartender", (1,))
    by_name = {c.name: c for c in gap.candidates}
    assert {name: c.reason for name, c in by_name.items()} == {
        "Jade": "unavailable",
        "Ravi": "max_hours",
        "Tharindu": "busy",
    }
    assert "Sam" not in by_name  # no bartender skill
    assert by_name["Tharindu"].other_shift_id == PATIO.id
    assert (by_name["Ravi"].worked_minutes, by_name["Ravi"].max_hours) == (0, 4)
    assert not gap.anyone_free
    assert not explanation.together_only
    assert explanation.blocking == (gap,)


def test_reason_text_is_short():
    [gap] = _explain([OMAR, JADE, THARINDU, RAVI]).gaps
    shifts_by_id = {shift.id: shift for shift in SHIFTS}

    texts = {c.name: reason_text(c, shifts_by_id, UTC) for c in gap.candidates}

    assert texts == {
        "Jade": "not available",
        "Ravi": "at max hours (0 of 4 h)",
        "Tharindu": "working Sat 28 17:00-23:00",
    }


def test_summary_lists_actionable_reasons_first():
    employees = [OMAR, JADE, THARINDU, RAVI]
    names = {e.id: e.name for e in employees}

    text = summarize(_explain(employees), SHIFTS, UTC, names)

    assert text == (
        "Omar is off Sat 28 17:00-23:00 (bartender). Other bartenders: "
        "Tharindu (working Sat 28 17:00-23:00), Ravi (at max hours (0 of 4 h)), "
        "Jade (not available)."
    )


def test_nobody_else_with_the_skill():
    text = summarize(_explain([OMAR, SAM]), SHIFTS, UTC, {1: "Omar", 5: "Sam"})
    assert text.endswith("and nobody else works bartender.")


def test_a_free_person_means_it_is_the_combination():
    lena = _employee(6, "Lena")
    explanation = _explain([OMAR, JADE, lena])
    [gap] = explanation.gaps

    assert gap.anyone_free
    assert explanation.together_only
    assert {c.name: c.reason for c in gap.candidates}["Lena"] is None


def test_explanation_agrees_with_the_solver():
    """When the explanation says nobody can fill the gap, the solver agrees.

    Like a real call-out, Omar is off every shift for the rest of the day.
    """
    employees = [OMAR, JADE, THARINDU, RAVI]
    rest_of_day = {1: [1], 2: [1]}
    [gap] = _explain(employees, rest_of_day).gaps
    result = engine.repair(
        employees=employees,
        shifts=SHIFTS,
        policy=POLICY,
        original_schedule=ORIGINAL,
        excluded_assignments=rest_of_day,
        deterministic=True,
    )
    assert not gap.anyone_free
    assert result.assignments is None


def test_shift_label_uses_restaurant_time():
    assert shift_label(BAR, ZoneInfo("Asia/Colombo")) == "Sat 28 22:30-04:30"
