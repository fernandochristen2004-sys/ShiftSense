from optimizer.models import Shift

def shifts_violate_minimum_rest(
    first_shift: Shift,
    second_shift: Shift,
    minimum_rest_hours: int,
) -> bool:
    """Check whether two non-overlapping shifts violate minimum rest."""

    first_start = first_shift.day * 24 + first_shift.start_hour
    first_end = first_shift.day * 24 + first_shift.end_hour

    second_start = second_shift.day * 24 + second_shift.start_hour
    second_end = second_shift.day * 24 + second_shift.end_hour

    # Put the shifts in chronological order.
    if first_start > second_start:
        first_start, second_start = second_start, first_start
        first_end, second_end = second_end, first_end

    # Overlapping shifts are handled by a separate constraint.
    if first_end > second_start:
        return False

    rest_hours = second_start - first_end

    return rest_hours < minimum_rest_hours