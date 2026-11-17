"""M0-13b: exact binomial intervals and the cluster bootstrap.

Expected values come from closed forms written out here, from the defining
property of the interval checked with `math.comb`, and from published
Clopper-Pearson values.
"""

import math
from pathlib import Path

import pytest

from utux.errors import GoldSetError
from utux.evalkit.gold import read_gold_release
from utux.evalkit.intervals import claim_clusters, cluster_bootstrap, exact_binomial_interval

RELEASE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "gold_release" / "synthetic_release.jsonl"
)


def _upper_tail(x: int, n: int, p: float) -> float:
    """P(X >= x) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(x, n + 1))


def _lower_tail(x: int, n: int, p: float) -> float:
    """P(X <= x) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(0, x + 1))


@pytest.mark.parametrize("n", [1, 10, 30, 150])
def test_zero_errors_use_the_closed_form(n: int) -> None:
    interval = exact_binomial_interval(0, n)
    assert interval.lower == 0.0
    # The maintainer's closed form: 1 - (alpha / 2) ** (1 / n).
    assert interval.upper == pytest.approx(1 - 0.025 ** (1 / n), abs=1e-12)


def test_zero_errors_in_150_items_give_an_upper_bound_near_2_4_percent() -> None:
    # 1 - 0.025 ** (1/150) = 0.0242926 (RFC-002 section 3: about 3 / n).
    assert exact_binomial_interval(0, 150).upper == pytest.approx(0.0242926, abs=1e-7)


@pytest.mark.parametrize("n", [1, 10, 150])
def test_all_errors_use_the_mirror_closed_form(n: int) -> None:
    interval = exact_binomial_interval(n, n)
    assert interval.lower == pytest.approx(0.025 ** (1 / n), abs=1e-12)
    assert interval.upper == 1.0


@pytest.mark.parametrize(("x", "n"), [(1, 10), (2, 5), (5, 10), (7, 200), (1, 2)])
def test_bounds_have_the_defining_tail_probabilities(x: int, n: int) -> None:
    interval = exact_binomial_interval(x, n)
    # Clopper-Pearson: P(X >= x | lower) = alpha/2 and P(X <= x | upper) = alpha/2.
    assert _upper_tail(x, n, interval.lower) == pytest.approx(0.025, abs=1e-9)
    assert _lower_tail(x, n, interval.upper) == pytest.approx(0.025, abs=1e-9)


def test_published_value_for_five_of_ten() -> None:
    # Clopper-Pearson 95% for 5/10: 0.1871 to 0.8129.
    interval = exact_binomial_interval(5, 10)
    assert interval.lower == pytest.approx(0.1871, abs=1e-4)
    assert interval.upper == pytest.approx(0.8129, abs=1e-4)


def test_one_of_ten_lower_bound_has_a_closed_form() -> None:
    # P(X >= 1) = 1 - (1 - p)^10 = 0.025, so p = 1 - 0.975 ** (1/10).
    assert exact_binomial_interval(1, 10).lower == pytest.approx(1 - 0.975**0.1, abs=1e-12)


def test_other_confidence_levels() -> None:
    assert exact_binomial_interval(0, 10, alpha=0.1).upper == pytest.approx(1 - 0.05**0.1)


@pytest.mark.parametrize(
    ("x", "n", "alpha"), [(0, 0, 0.05), (3, 2, 0.05), (-1, 5, 0.05), (1, 5, 0.0), (1, 5, 1.0)]
)
def test_invalid_inputs_are_refused(x: int, n: int, alpha: float) -> None:
    with pytest.raises(GoldSetError):
        exact_binomial_interval(x, n, alpha=alpha)


# Cluster bootstrap


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def test_same_seed_gives_the_same_interval() -> None:
    clusters = {"a": [0.0, 1.0], "b": [1.0], "c": [0.0, 0.0, 1.0]}
    first = cluster_bootstrap(clusters, _mean, replicates=500, seed=11)
    second = cluster_bootstrap(clusters, _mean, replicates=500, seed=11)
    assert first == second


def test_one_cluster_gives_the_statistic_itself() -> None:
    # Every replicate draws the only cluster, so every replicate mean is 0.5.
    interval = cluster_bootstrap({"a": [0.0, 1.0]}, _mean, replicates=200, seed=1)
    assert (interval.lower, interval.upper) == (0.5, 0.5)
    assert interval.estimate == 0.5


def test_replicates_resample_whole_clusters() -> None:
    # Two clusters of one value each: a replicate draws two clusters, so its
    # mean is 0, 0.5 or 1. Never a mean that splits a cluster.
    interval = cluster_bootstrap({"a": [0.0], "b": [1.0]}, _mean, replicates=300, seed=3)
    assert interval.lower in (0.0, 0.5, 1.0)
    assert interval.upper in (0.0, 0.5, 1.0)
    assert interval.lower <= interval.estimate <= interval.upper


def test_undefined_replicates_are_counted_not_used() -> None:
    def first_value(values: list[float]) -> float | None:
        return values[0] if values and values[0] > 0 else None

    interval = cluster_bootstrap({"a": [0.0], "b": [1.0]}, first_value, replicates=100, seed=5)
    assert interval.undefined + interval.used == 100
    assert interval.undefined > 0


def test_bootstrap_needs_clusters_and_replicates() -> None:
    with pytest.raises(GoldSetError):
        cluster_bootstrap({}, _mean, replicates=10, seed=0)
    with pytest.raises(GoldSetError):
        cluster_bootstrap({"a": [1.0]}, _mean, replicates=0, seed=0)


def test_claims_are_clustered_by_linked_source_groups() -> None:
    clusters = claim_clusters(read_gold_release(RELEASE))
    # The groups of the split: G9002, G9003 and G9004 share one cluster.
    assert clusters["G9002-c1"] == clusters["G9003-c1"] == clusters["G9004-c1"]
    assert clusters["G9000-c1"] == clusters["G9001-c1"]
    assert clusters["G9007-c1"] != clusters["G9008-c1"]
    assert len(set(clusters.values())) == 6
