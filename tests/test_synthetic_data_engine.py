"""Integration tests for synthetic restaurants and the real engine."""

import pytest

from optimizer import engine
from optimizer.input_validator import validate_scheduling_inputs
from optimizer.synthetic_data import generate_restaurant_scenario


def _generate(scenario):
    return engine.generate(
        employees=list(scenario.employees),
        shifts=list(scenario.shifts),
        policy=scenario.policy,
    )


@pytest.mark.parametrize("employee_count", [10, 25, 40])
def test_generated_data_passes_input_validation(employee_count):
    scenario = generate_restaurant_scenario(employee_count)

    # Raises ValueError if the generated dataset is invalid.
    validate_scheduling_inputs(
        employees=list(scenario.employees),
        shifts=list(scenario.shifts),
    )


@pytest.mark.parametrize("employee_count", [25, 40])
@pytest.mark.parametrize("seed", [42, 0, 1, 2, 3])
def test_engine_schedules_realistic_restaurant(employee_count, seed):
    """Restaurants of 25+ staff are solvable, so a valid schedule must come back."""
    result = _generate(generate_restaurant_scenario(employee_count, seed=seed))

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None

    # Every returned schedule must satisfy hard constraints.
    assert result.validation_errors == ()

    # Shortages are allowed but must be reported accurately.
    assert result.fully_covered == (len(result.shortages) == 0)


def test_engine_handles_overloaded_small_restaurant():
    """A 10-person restaurant is usually overloaded by the shift pattern."""
    result = _generate(generate_restaurant_scenario(10))

    # Either a short-staffed schedule or a proven-impossible minimum
    # is acceptable. A timeout is not.
    assert result.status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")

    if result.assignments is not None:
        assert result.validation_errors == ()
        assert result.fully_covered == (len(result.shortages) == 0)
    else:
        assert result.fully_covered is None
        assert result.shortages == ()


@pytest.mark.parametrize("employee_count", [25, 40])
def test_engine_solves_guaranteed_feasible_scenario(employee_count):
    scenario = generate_restaurant_scenario(
        employee_count=employee_count,
        days=7,
        seed=42,
        mode="feasible",
    )

    assert scenario.reference_schedule is not None

    result = _generate(scenario)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments is not None
    assert result.validation_errors == ()

    # Every staffing target should be achievable.
    assert result.fully_covered is True
    assert result.shortages == ()
