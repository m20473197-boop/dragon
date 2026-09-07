"""Tiny randomness helpers shared across game modules."""
from __future__ import annotations

import random as _random
from typing import Mapping, TypeVar

T = TypeVar("T")


def weighted_choice(weights: Mapping[T, float]) -> T:
    """Return one key from ``weights``, chosen proportionally to its weight.

    Example::

        weighted_choice({"rabbit": 50, "deer": 20})  # -> "rabbit" most of the time
    """
    keys = list(weights.keys())
    return _random.choices(keys, weights=[weights[k] for k in keys], k=1)[0]
