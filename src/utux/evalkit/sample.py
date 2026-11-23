"""The gold v0 sample and its splits (M0-15c, gold v0 strategy, section 9).

The sample is drawn by a fixed, recorded seed:

- 150 SciFact items, 50 of each status (`verified`, `contradicted`,
  `insufficient_evidence`);
- 100 SciClaimEval ML items, 50 `verified` and 50 `contradicted`;
- about 50 perturbations whose parents are in the sample, ML first where the
  type allows, at most 10 uncited abstracts.

The items are split into `dev` and `test` by source group with
`assign_splits`; a perturbation goes with its parent (RFC-002, section 6).
Reports hold counts only.
"""

import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from utux.errors import GoldSetError
from utux.evalkit.annotation import with_splits
from utux.evalkit.gold import (
    Domain,
    GoldItem,
    GoldStatus,
    Origin,
    PerturbationRecord,
    PublicDataset,
)
from utux.evalkit.perturb import MAX_UNCITED, PerturbationType
from utux.evalkit.splits import assign_splits

DEV_SHARE = 0.3
"""The share of items in `dev` (RFC-002, section 6)."""


@dataclass(frozen=True)
class SampleSizes:
    """How many items of each kind the sample takes."""

    scifact_per_status: int = 50
    sciclaimeval_ml_per_status: int = 50
    perturbations: int = 50
    max_uncited: int = MAX_UNCITED


_SCIFACT_STATUSES = (
    GoldStatus.VERIFIED,
    GoldStatus.CONTRADICTED,
    GoldStatus.INSUFFICIENT_EVIDENCE,
)
_SCICLAIMEVAL_STATUSES = (GoldStatus.VERIFIED, GoldStatus.CONTRADICTED)


def _dataset(item: GoldItem) -> PublicDataset | None:
    return item.provenance.dataset if item.provenance is not None else None


def select_imported(
    items: Sequence[GoldItem], sizes: SampleSizes, *, seed: int
) -> tuple[GoldItem, ...]:
    """The imported items of the sample, stratified by dataset and status.

    Raises:
        GoldSetError: A stratum has fewer items than the sample needs.
    """
    rng = random.Random(seed)
    public = sorted((i for i in items if i.origin is Origin.PUBLIC), key=lambda i: i.item_id)
    strata = [
        (PublicDataset.SCIFACT, None, status, sizes.scifact_per_status)
        for status in _SCIFACT_STATUSES
    ] + [
        (PublicDataset.SCICLAIMEVAL, Domain.ML, status, sizes.sciclaimeval_ml_per_status)
        for status in _SCICLAIMEVAL_STATUSES
    ]
    chosen: list[GoldItem] = []
    for dataset, domain, status, wanted in strata:
        pool = [
            i
            for i in public
            if _dataset(i) is dataset
            and (domain is None or i.domain is domain)
            and i.claims[0].status is status
        ]
        if len(pool) < wanted:
            raise GoldSetError(
                f"only {len(pool)} {dataset.value} items are {status.value}; the sample "
                f"needs {wanted}"
            )
        chosen += rng.sample(pool, wanted)
    return tuple(sorted(chosen, key=lambda i: i.item_id))


def _parent(item: GoldItem) -> str | None:
    return item.hidden.source_item if isinstance(item.hidden, PerturbationRecord) else None


def select_perturbations(
    perturbed: Sequence[GoldItem],
    parents: Sequence[GoldItem],
    sizes: SampleSizes,
    *,
    seed: int,
) -> tuple[GoldItem, ...]:
    """About `sizes.perturbations` children of the chosen parents, by type in turn.

    Within each type, children of ML parents come first, each group in an
    order shuffled by `seed`. The uncited abstract is capped.
    """
    rng = random.Random(seed)
    chosen_ids = {p.item_id for p in parents}
    queues: dict[PerturbationType, list[GoldItem]] = {}
    for kind in PerturbationType:
        pool = sorted(
            (c for c in perturbed if PerturbationType.of(c) is kind and _parent(c) in chosen_ids),
            key=lambda c: c.item_id,
        )
        ml = [c for c in pool if c.domain is Domain.ML]
        others = [c for c in pool if c.domain is not Domain.ML]
        rng.shuffle(ml)
        rng.shuffle(others)
        queue = ml + others
        if kind is PerturbationType.UNCITED_ABSTRACT:
            queue = queue[: sizes.max_uncited]
        queues[kind] = queue
    picked: list[GoldItem] = []
    while len(picked) < sizes.perturbations and any(queues.values()):
        for kind in PerturbationType:
            if queues[kind] and len(picked) < sizes.perturbations:
                picked.append(queues[kind].pop(0))
    return tuple(sorted(picked, key=lambda c: c.item_id))


@dataclass(frozen=True)
class V0Sample:
    """The v0 items with their splits, and how they were drawn."""

    items: tuple[GoldItem, ...]
    seed: int
    dev_share: float
    sizes: SampleSizes

    def report(self) -> dict[str, object]:
        """Counts only, per split: origin, status, domain and confirmation."""
        by_split: dict[str, dict[str, Counter[str]]] = {}
        for item in self.items:
            split = item.split.value if item.split is not None else "none"
            counts = by_split.setdefault(
                split, {key: Counter() for key in ("origin", "status", "domain", "confirmation")}
            )
            counts["origin"][item.origin.value] += 1
            counts["status"][item.claims[0].status.value] += 1
            counts["domain"][item.domain.value] += 1
            hidden = item.hidden
            confirmation = (
                hidden.confirmation.value if isinstance(hidden, PerturbationRecord) else "imported"
            )
            counts["confirmation"][confirmation] += 1
        ml = sum(1 for i in self.items if i.domain is Domain.ML)
        return {
            "seed": self.seed,
            "dev_share": self.dev_share,
            "sizes": vars(self.sizes),
            "items": len(self.items),
            "ml_share": round(ml / len(self.items), 4) if self.items else None,
            "by_split": {
                split: {key: dict(sorted(c.items())) for key, c in counts.items()}
                for split, counts in sorted(by_split.items())
            },
        }


def sample_v0(
    imported: Sequence[GoldItem],
    perturbed: Sequence[GoldItem],
    sizes: SampleSizes,
    *,
    seed: int,
    dev_share: float = DEV_SHARE,
) -> V0Sample:
    """Draw the v0 sample and split it by source group, all by `seed`.

    Raises:
        GoldSetError: A stratum is too small, or the split fails.
    """
    parents = select_imported(imported, sizes, seed=seed)
    children = select_perturbations(perturbed, parents, sizes, seed=seed)
    items = (*parents, *children)
    splits = assign_splits(items, dev_share=dev_share, seed=seed)
    return V0Sample(with_splits(items, splits), seed, dev_share, sizes)
