"""Execution accuracy metric: compare SQL result sets as Python sets."""

from typing import Optional


def score(gold: Optional[set], pred: Optional[set]) -> float:
    """Return 1.0 if result sets match exactly, 0.0 otherwise."""
    if gold is None or pred is None:
        return 0.0
    return 1.0 if gold == pred else 0.0
