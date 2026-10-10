import math
from collections.abc import Sequence


def first_relevant_rank(retrieved_pages: Sequence[int | None], relevant: set[int]) -> int | None:
    """1-based rank of the first retrieved chunk whose page is relevant, or None."""
    for rank, page in enumerate(retrieved_pages, start=1):
        if page in relevant:
            return rank
    return None


def hit_at_k(rank: int | None, k: int) -> float:
    return 1.0 if rank is not None and rank <= k else 0.0


def reciprocal_rank(rank: int | None, k: int = 10) -> float:
    return 1.0 / rank if rank is not None and rank <= k else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile: the smallest value with at least pct% of samples at or below it."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[index]
