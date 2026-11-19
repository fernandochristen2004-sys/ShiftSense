from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from optimizer.engine import generate, repair
from optimizer.models import (
    DateTimeShift,
    Employee,
    SchedulingPolicy,
    ShiftRequirement,
)

def make_engine_test_data():
    start = datetime(2026, 11, 23, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)

    employees = [
        Employee(
            id=employee_id,
            name=f"Employee {employee_id}",
            skills=frozenset({"server"}),
            max_hours=8,
            datetime_availability=((start, end),),
        )
        for employee_id in (1, 2)
    ]

    shifts = [
        DateTimeShift(
            id=1,
            starts_at=start,
            ends_at=end,
            requirements=(
                ShiftRequirement("server", 2, min_count=1),
            ),
        )
    ]

    return employees, shifts


def test_engine_generate_valid_schedule():
    employees, shifts = make_engine_test_data()

    result = generate(
        employees,
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"server": [1, 2]},
    }
    assert result.fully_covered is True
    assert result.shortages == ()
    assert result.assignment_changes is None
    assert result.validation_errors == ()


def test_engine_repair_valid_schedule():
    employees, shifts = make_engine_test_data()

    original_schedule = {
        1: {"server": [1]},
    }

    result = repair(
        employees,
        shifts,
        policy=SchedulingPolicy(
            allow_partial_coverage=True,
            fairness_enabled=False,
        ),
        original_schedule=original_schedule,
    )

    assert result.status == "OPTIMAL"
    assert result.assignments == {
        1: {"server": [1, 2]},
    }
    assert result.fully_covered is True
    assert result.shortages == ()
    assert result.assignment_changes == 1
    assert result.validation_errors == ()


def test_engine_rejects_invalid_input_before_solving():
    employees, shifts = make_engine_test_data()

    invalid_employees = [
        employees[0],
        employees[0],
    ]

    with patch(
        "optimizer.solver.cp_model.CpSolver.solve"
    ) as mocked_solve:
        with pytest.raises(
            ValueError,
            match="Duplicate employee IDs",
        ):
            generate(
                invalid_employees,
                shifts,
                policy=SchedulingPolicy(),
            )

    mocked_solve.assert_not_called()


def test_engine_surfaces_independent_validation_errors():
    employees, shifts = make_engine_test_data()

    with patch(
        "optimizer.engine.validate_schedule",
        return_value=["Simulated rule violation"],
    ):
        result = generate(
            employees,
            shifts,
            policy=SchedulingPolicy(
                allow_partial_coverage=True,
                fairness_enabled=False,
            ),
        )

    assert result.status == "OPTIMAL"
    assert result.assignments is not None
    assert result.validation_errors == (
        "Simulated rule violation",
    )
