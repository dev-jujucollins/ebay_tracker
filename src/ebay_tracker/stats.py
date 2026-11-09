"""Summary statistics for a sample of prices.

The median is the headline number: unlike the mean it barely moves when a few
accessories or damaged units slip through the search filters.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PriceSummary:
    count: int
    low: float
    p25: float
    median: float
    mean: float


def percentile(sorted_prices: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already sorted, non-empty sample."""
    if not sorted_prices:
        raise ValueError("percentile() needs at least one price")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between 0 and 1")

    position = (len(sorted_prices) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(sorted_prices) - 1)
    weight = position - lower
    return sorted_prices[lower] * (1 - weight) + sorted_prices[upper] * weight


def summarize(prices: Sequence[float]) -> PriceSummary | None:
    """Summarize a price sample, or return None when it is empty."""
    if not prices:
        return None

    ordered = sorted(prices)
    return PriceSummary(
        count=len(ordered),
        low=ordered[0],
        p25=percentile(ordered, 0.25),
        median=statistics.median(ordered),
        mean=statistics.fmean(ordered),
    )
