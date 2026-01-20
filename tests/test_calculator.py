import pytest

from demo_app.calculator import RangeStats, add, divide, mean


def test_add() -> None:
    assert add(1, 2) == 3


def test_divide() -> None:
    assert divide(10, 2) == 5


def test_divide_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


def test_mean() -> None:
    assert mean([1, 2, 3, 4]) == 2.5


def test_mean_ignores_none_values() -> None:
    # BUG (seed/issue-2): mean() should ignore None entries.
    assert mean([1.0, None, 2.0]) == 1.5  # type: ignore[list-item]


def test_mean_empty_raises() -> None:
    with pytest.raises(ValueError):
        mean([])


def test_range_stats() -> None:
    rs = RangeStats(1, 3)
    assert rs.count() == 3
    assert rs.total() == 6

