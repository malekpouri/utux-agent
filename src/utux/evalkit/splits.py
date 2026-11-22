"""The group-aware split of a gold release (RFC-002, section 6).

Items are split by `source_group`, never one by one: every item that shares
a source group with another, directly or through a chain of items, goes to
the same split. A perturbed item stays with the natural item it was made
from, even when it is attached to a different paper.

The split reads item ids, source groups and the origin link only. It never
reads or changes a label. The split report reads labels only to count them,
and shows no item text.
"""

import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from utux.errors import GoldSetError
from utux.evalkit.gold import (
    Domain,
    GoldItem,
    GoldSplit,
    GoldStatus,
    HardCase,
    Origin,
    PerturbationRecord,
)
from utux.schemas.claim_ledger import CheckedText, ScopeFlag


def split_groups(items: Sequence[GoldItem]) -> list[frozenset[str]]:
    """Return the sets of item ids that must share a split.

    Two items are in one set when they cite a source of the same source
    group, or when one is the origin of the other; the sets are the
    connected parts of that relation. They are sorted by their smallest item
    id.

    Raises:
        GoldSetError: An item id appears twice, or a perturbed item's origin
            is not among the items.
    """
    parent: dict[str, str] = {}
    for item in items:
        if item.item_id in parent:
            raise GoldSetError(f"the item id {item.item_id} appears more than once")
        parent[item.item_id] = item.item_id

    def root(item_id: str) -> str:
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    def join(first: str, second: str) -> None:
        a, b = root(first), root(second)
        if a != b:
            parent[max(a, b)] = min(a, b)

    first_of_group: dict[str, str] = {}
    for item in items:
        for _, _, pair in item.pairs():
            join(item.item_id, first_of_group.setdefault(pair.source_group, item.item_id))
        if isinstance(item.hidden, PerturbationRecord):
            origin = item.hidden.source_item
            if origin not in parent:
                raise GoldSetError(
                    f"the perturbed item {item.item_id} was made from {origin}, "
                    "which is not among the items"
                )
            join(item.item_id, origin)

    groups: dict[str, set[str]] = {}
    for item_id in parent:
        groups.setdefault(root(item_id), set()).add(item_id)
    return sorted((frozenset(group) for group in groups.values()), key=min)


def assign_splits(
    items: Sequence[GoldItem], *, dev_share: float, seed: int
) -> dict[str, GoldSplit]:
    """Assign every item to `dev` or `test`, keeping each group together.

    The groups of `split_groups` are shuffled with `random.Random(seed)`. In
    that order, a group goes to `dev` if it fits in what is left of the
    target, `round(dev_share * len(items))` items, and to `test` otherwise.
    The same items and seed always give the same result. The split already
    stored in the items is ignored. Strata (RFC-002, section 3) are not
    balanced.

    Args:
        items: The items of the release.
        dev_share: The share of items wanted in `dev`, between 0 and 1.
        seed: The seed of the shuffle.

    Returns:
        The split of each item id, in the order of the items.

    Raises:
        GoldSetError: `dev_share` is not between 0 and 1, or `split_groups`
            fails.
    """
    if not 0 < dev_share < 1:
        raise GoldSetError(f"dev_share must be between 0 and 1, exclusive; got {dev_share}")
    groups = split_groups(items)
    random.Random(seed).shuffle(groups)
    target = round(dev_share * len(items))
    in_dev = 0
    split_of: dict[str, GoldSplit] = {}
    for group in groups:
        if in_dev + len(group) <= target:
            in_dev += len(group)
            split = GoldSplit.DEV
        else:
            split = GoldSplit.TEST
        for item_id in group:
            split_of[item_id] = split
    return {item.item_id: split_of[item.item_id] for item in items}


NO_HARD_CASE = "none"

# Each stratum of RFC-002, section 3: its key, its heading, its unit, its
# values, and the values one item contributes.
_Values = Callable[[GoldItem], Iterable[str]]
_STRATA: tuple[tuple[str, str, str, tuple[str, ...], _Values], ...] = (
    (
        "gold_status",
        "Gold status",
        "claim",
        tuple(status.value for status in GoldStatus),
        lambda item: (claim.status.value for claim in item.claims),
    ),
    (
        "scope_flag",
        "Scope flag",
        "pair",
        tuple(flag.value for flag in ScopeFlag),
        lambda item: (flag.value for _, _, pair in item.pairs() for flag in pair.scope_flags),
    ),
    (
        "domain",
        "Domain",
        "item",
        tuple(domain.value for domain in Domain),
        lambda item: (item.domain.value,),
    ),
    (
        "evidence_text",
        "Evidence text",
        "pair",
        tuple(checked.value for checked in CheckedText),
        lambda item: (pair.checked_text.value for _, _, pair in item.pairs()),
    ),
    (
        "item_source",
        "Item source",
        "item",
        tuple(origin.value for origin in Origin),
        lambda item: (item.origin.value,),
    ),
    (
        "hard_case",
        "Hard case",
        "item",
        (*(case.value for case in HardCase), NO_HARD_CASE),
        lambda item: (NO_HARD_CASE if item.hard_case is None else item.hard_case.value,),
    ),
)


@dataclass(frozen=True)
class SplitReport:
    """Counts per stratum in each split, to judge a split before it is used.

    Attributes:
        items: The number of items in each split.
        counts: For each split, for each stratum, the count of each value.
            Gold status is counted per claim, scope flag and evidence text
            per pair, domain, item source and hard case per item.
    """

    items: dict[GoldSplit, int]
    counts: dict[GoldSplit, dict[str, dict[str, int]]]

    @property
    def dev_share(self) -> float:
        """The share of items in `dev`."""
        return self.items[GoldSplit.DEV] / sum(self.items.values())

    def to_json(self) -> dict[str, object]:
        """Return the report as a JSON object. It holds counts only."""
        return {
            "items": {split.value: count for split, count in self.items.items()},
            "dev_share": self.dev_share,
            **{split.value: counts for split, counts in self.counts.items()},
        }

    def lines(self) -> list[str]:
        """Return the report as lines of text. They hold counts only."""
        dev, test = self.counts[GoldSplit.DEV], self.counts[GoldSplit.TEST]
        lines = [
            f"Items: dev {self.items[GoldSplit.DEV]}, test {self.items[GoldSplit.TEST]}. "
            f"Dev share: {self.dev_share:.3f}"
        ]
        for key, heading, unit, values, _ in _STRATA:
            lines.append(f"{heading} (per {unit}):")
            lines += [
                f"  {value}: dev {dev[key][value]}, test {test[key][value]}" for value in values
            ]
        return lines


def split_report(items: Sequence[GoldItem]) -> SplitReport:
    """Count, for each split, the values of every stratum of RFC-002, section 3.

    Every value of a stratum is listed, with zero where it does not occur, so
    that the two splits can be compared line by line.

    Raises:
        GoldSetError: There are no items, or an item has no split yet; set
            the splits first (`utux.evalkit.annotation.with_splits`).
    """
    if not items:
        raise GoldSetError("the release has no items to report on")
    unset = [item.item_id for item in items if item.split is None]
    if unset:
        raise GoldSetError(
            f"{len(unset)} items have no split yet, the first {unset[0]}; set the splits "
            "first, from assign_splits"
        )
    counts: dict[GoldSplit, dict[str, dict[str, int]]] = {
        split: {key: dict.fromkeys(values, 0) for key, _, _, values, _ in _STRATA}
        for split in GoldSplit
    }
    sizes = dict.fromkeys(GoldSplit, 0)
    for item in items:
        split = item.split
        assert split is not None
        sizes[split] += 1
        for key, _, _, _, values_of in _STRATA:
            for value in values_of(item):
                counts[split][key][value] += 1
    return SplitReport(sizes, counts)
