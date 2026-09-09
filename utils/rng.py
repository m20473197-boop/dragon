"""Tiny randomness helpers shared across game modules."""
from __future__ import annotations

import random as _random
from typing import Mapping, Optional, TypeVar

T = TypeVar("T")


def weighted_choice(
    weights: Mapping[T, float], rng: Optional[_random.Random] = None
) -> T:
    """Return one key from ``weights``, chosen proportionally to its weight.

    Pass ``rng`` (a ``random.Random``) to make the draw reproducible; it
    defaults to the shared module-level generator.

    Example::

        weighted_choice({"rabbit": 50, "deer": 20})  # -> "rabbit" most of the time
    """
    keys = list(weights.keys())
    chooser = rng.choices if rng is not None else _random.choices
    return chooser(keys, weights=[weights[k] for k in keys], k=1)[0]
