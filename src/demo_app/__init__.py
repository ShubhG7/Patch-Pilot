"""Demo application package used as deterministic PatchPilot playground."""

from .calculator import add, divide, mean
from .text_utils import normalize_whitespace, slugify_title

__all__ = [
    "add",
    "divide",
    "mean",
    "normalize_whitespace",
    "slugify_title",
]

