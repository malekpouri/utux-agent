"""The group-aware split of a gold release (RFC-002, section 6).

Items are split by `source_group`, never one by one: every item that shares
a source group with another, directly or through a chain of items, goes to
the same split. A perturbed item stays with the natural item it was made
from, even when it is attached to a different paper.

The split reads item ids, source groups and the origin link only. It never
reads or changes a label.
"""

import random
from collections.abc import Sequence

from utux.errors import GoldSetError
from utux.evalkit.gold import GoldItem, GoldSplit


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
        if item.hidden is not None:
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
