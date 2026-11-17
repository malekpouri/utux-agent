"""Interval estimates (RFC-002, section 8): exact binomial and cluster bootstrap.

Standard library only. The exact interval is the Clopper-Pearson interval,
found by bisection on the binomial tail probabilities, with the closed forms
at zero and at all errors. The bootstrap resamples whole clusters, because
claims that share a source group are not independent.
"""

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from utux.errors import GoldSetError
from utux.evalkit.gold import GoldItem
from utux.evalkit.splits import split_groups


@dataclass(frozen=True)
class BinomialInterval:
    """A two-sided interval for a proportion."""

    lower: float
    upper: float


def _upper_tail(x: int, n: int, p: float) -> float:
    """P(X >= x) for X ~ Binomial(n, p)."""
    return math.fsum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(x, n + 1))


def _bisect(increasing: Callable[[float], float], target: float) -> float:
    """Find p in [0, 1] with increasing(p) == target, to double precision."""
    low, high = 0.0, 1.0
    for _ in range(200):
        middle = (low + high) / 2
        if middle in (low, high):
            break
        if increasing(middle) < target:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def exact_binomial_interval(x: int, n: int, *, alpha: float = 0.05) -> BinomialInterval:
    """Return the exact (Clopper-Pearson) interval for x events in n trials.

    The lower bound p_L solves P(X >= x | p_L) = alpha/2 and the upper bound
    p_U solves P(X <= x | p_U) = alpha/2. With no events the lower bound is 0
    and the upper bound is 1 - (alpha/2)^(1/n); with n events the lower bound
    is (alpha/2)^(1/n) and the upper bound is 1. It stays valid when n is
    small or no event is observed.

    Raises:
        GoldSetError: n is not positive, x is outside 0 to n, or alpha is not
            between 0 and 1.
    """
    if n < 1 or not 0 <= x <= n:
        raise GoldSetError(f"an exact interval needs 0 <= x <= n and n >= 1; got x={x}, n={n}")
    if not 0 < alpha < 1:
        raise GoldSetError(f"alpha must be between 0 and 1; got {alpha}")
    half = alpha / 2
    if x == 0:
        lower = 0.0
    elif x == n:
        lower = half ** (1 / n)
    else:
        lower = _bisect(lambda p: _upper_tail(x, n, p), half)
    if x == n:
        upper = 1.0
    elif x == 0:
        upper = 1 - half ** (1 / n)
    else:
        # P(X <= x) = 1 - P(X >= x + 1), which falls as p grows.
        upper = _bisect(lambda p: _upper_tail(x + 1, n, p), 1 - half)
    return BinomialInterval(lower, upper)


@dataclass(frozen=True)
class BootstrapInterval:
    """A percentile interval from a cluster bootstrap.

    Attributes:
        estimate: The statistic on all units, or None if it is undefined.
        lower: The alpha/2 percentile of the defined replicates, or None.
        upper: The 1 - alpha/2 percentile of the defined replicates, or None.
        used: Replicates whose statistic was defined.
        undefined: Replicates whose statistic was undefined, for example a
            rate with no denominator. They are counted, not used.
    """

    estimate: float | None
    lower: float | None
    upper: float | None
    used: int
    undefined: int


def cluster_bootstrap[T](
    clusters: Mapping[str, Sequence[T]],
    statistic: Callable[[list[T]], float | None],
    *,
    replicates: int,
    seed: int,
    alpha: float = 0.05,
) -> BootstrapInterval:
    """Resample whole clusters with replacement and return a percentile interval.

    Each replicate draws as many clusters as there are, with replacement,
    using `random.Random(seed)` over the clusters in sorted order, and
    computes `statistic` on all units of the drawn clusters. The lower bound
    is the replicate at index floor(alpha/2 * m) of the m sorted defined
    replicates, and the upper bound the one at index ceil((1 - alpha/2) * m)
    - 1. The same inputs and seed always give the same interval.

    Raises:
        GoldSetError: There are no clusters, replicates is not positive, or
            alpha is not between 0 and 1.
    """
    if not clusters:
        raise GoldSetError("the bootstrap needs at least one cluster")
    if replicates < 1:
        raise GoldSetError(f"replicates must be at least 1; got {replicates}")
    if not 0 < alpha < 1:
        raise GoldSetError(f"alpha must be between 0 and 1; got {alpha}")
    names = sorted(clusters)
    estimate = statistic([unit for name in names for unit in clusters[name]])
    rng = random.Random(seed)
    values: list[float] = []
    undefined = 0
    for _ in range(replicates):
        drawn = rng.choices(names, k=len(names))
        value = statistic([unit for name in drawn for unit in clusters[name]])
        if value is None:
            undefined += 1
        else:
            values.append(value)
    if not values:
        return BootstrapInterval(estimate, None, None, 0, undefined)
    values.sort()
    m = len(values)
    lower = values[math.floor(alpha / 2 * m)]
    upper = values[max(0, math.ceil((1 - alpha / 2) * m) - 1)]
    return BootstrapInterval(estimate, lower, upper, m, undefined)


def claim_clusters(items: Sequence[GoldItem]) -> dict[str, str]:
    """Return the cluster of each claim id: its item's group of linked items.

    The clusters are the groups of `split_groups`: items that share a source
    group, directly or through other items, or a perturbed item and its
    origin. Each cluster is named by its smallest item id.
    """
    cluster_of_item = {item_id: min(group) for group in split_groups(items) for item_id in group}
    return {
        claim.claim_id: cluster_of_item[item.item_id] for item in items for claim in item.claims
    }
