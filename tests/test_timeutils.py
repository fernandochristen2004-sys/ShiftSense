import pytest

from optimizer.models import Shift
from optimizer.timeutils import shifts_violate_minimum_rest


@pytest.mark.parametrize(
    "first_day, first_end, second_day, second_start, "
    "minimum_rest, expected",
    [
        (0, 23, 1, 7, 11, True),
        (0, 23, 1, 10, 11, False),
        (0, 23, 1, 12, 11, False),
        (0, 17, 0, 20, 4, True),
        (0, 17, 0, 21, 4, False),
    ],
)
def test_minimum_rest_calculation(
    first_day,
    first_end,
    second_day,
    second_start,
    minimum_rest,
    expected,
):
    first_shift = Shift(
        id=1,
        day=first_day,
        start_hour=9,
        end_hour=first_end,
        required_staff=1,
        required_skill="server",
    )

    second_shift = Shift(
        id=2,
        day=second_day,
        start_hour=second_start,
        end_hour=23,
        required_staff=1,
        required_skill="server",
    )

    result = shifts_violate_minimum_rest(
        first_shift,
        second_shift,
        minimum_rest,
    )

    assert result is expected