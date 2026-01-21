from __future__ import annotations

from dataclasses import dataclass


def add(a: float, b: float) -> float:
    return a + b


def divide(a: float, b: float) -> float:
    """Divide a by b.

    Raises:
        ZeroDivisionError: if b is 0.
    """
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b


def mean(values: list[float]) -> float:
    """Return the arithmetic mean.

    Raises:
        ValueError: if values is empty.
    """
    if not values:
        raise ValueError("mean() requires at least one value")
    valid_values = [v for v in values if v is not None]
    return sum(valid_values) / len(valid_values)


@dataclass(frozen=True)
class RangeStats:
    """Simple stats over an inclusive integer range."""

    start: int
    end: int

    def count(self) -> int:
        if self.end < self.start:
            return 0
        return self.end - self.start + 1

    def total(self) -> int:
        if self.end < self.start:
            return 0
        # sum of arithmetic progression
        n = self.count()
        return n * (self.start + self.end) // 2

