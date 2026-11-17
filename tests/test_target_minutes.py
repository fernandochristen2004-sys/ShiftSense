import pytest

from optimizer.models import Employee
from optimizer.timeutils import hours_to_minutes


def make_employee(target_minutes=None, max_hours=20):
    return Employee(
        id=1,
        name="Alice",
        skills=frozenset({"cook"}),
        max_hours=max_hours,
        target_minutes=target_minutes,
    )


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (12.5, 750),
        (7.75, 465),
        (0, 0),
        ("22.5", 1350),
    ],
)
def test_hours_to_minutes(hours, expected):
    assert hours_to_minutes(hours) == expected


@pytest.mark.parametrize(
    "hours",
    [-1, 0.001, True, float("inf"), float("nan"), "abc"],
)
def test_invalid_hour_conversion(hours):
    with pytest.raises(ValueError):
        hours_to_minutes(hours)


@pytest.mark.parametrize(
    "target",
    [None, 0, 465, 750, 1200],
)
def test_valid_target_minutes(target):
    employee = make_employee(target_minutes=target)

    assert employee.target_minutes == target


def test_target_above_maximum_rejected():
    with pytest.raises(ValueError, match="exceed maximum"):
        make_employee(target_minutes=1201)


@pytest.mark.parametrize("target", [-1, 12.5, True, "750"])
def test_invalid_target_minutes(target):
    with pytest.raises(ValueError):
        make_employee(target_minutes=target)


def test_target_equal_to_maximum_allowed():
    employee = make_employee(
        target_minutes=hours_to_minutes(20),
        max_hours=20,
    )

    assert employee.target_minutes == 1200
