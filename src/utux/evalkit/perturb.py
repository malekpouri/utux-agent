"""Perturbations of gold v0 items whose labels follow from their construction (M0-15c).

Each perturbation takes a `verified` imported item, its parent, and changes
one thing (`docs/eval/gold-v0-strategy.md`, section 6). The label is set by
the construction, never by a model or by the agent:

- the parent's pair labels are kept, except where the type names one:
  `contradicts` for a number change and a direction reversal, and `neutral`
  for the uncited abstract;
- the type's scope flag is added to the pairs that supported the claim;
- the claim's status is the guideline's (`guideline_status`).

This module builds the four types that a fixed rule can make and check, with
no model: the uncited abstract, the number change, the hedge removal and the
metric swap. The four model-written types are in
`utux.evalkit.model_perturb`. A child item records its confirmation, its
target error and its parent in the hidden record, and keeps the parent's
provenance, licence and redistribution limit included.
"""

import random
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial

from utux.evalkit.gold import (
    Confirmation,
    Domain,
    ErrorClass,
    GoldItem,
    GoldPair,
    GoldStatus,
    NotScored,
    Origin,
    PerturbationRecord,
    PublicDataset,
    guideline_status,
)
from utux.schemas.claim_ledger import ScopeFlag, SourceLabel

HEDGES = (
    "possibly",
    "probably",
    "potentially",
    "perhaps",
    "presumably",
    "apparently",
    "seemingly",
    "conceivably",
    "plausibly",
    "arguably",
)
"""Hedge words whose removal leaves a grammatical sentence: adverbs only."""

METRIC_GROUPS: Mapping[str, tuple[str, ...]] = {
    "ml": ("accuracy", "precision", "recall", "F1", "BLEU", "ROUGE", "perplexity", "AUC"),
    "biomedicine": (
        "mortality",
        "incidence",
        "prevalence",
        "sensitivity",
        "specificity",
        "survival",
    ),
}
"""Metrics a claim may name; a swap replaces one with another of its group."""

MAX_UNCITED = 10
"""The cap on uncited-abstract perturbations (maintainer, 2026-11-22)."""

_NUMBER = re.compile(r"(?<![\w.\-/])(\d+(?:\.\d+)?)(?![\w\-/]|\.\d)")
_WORD = re.compile(r"[a-z0-9]{3,}")


class PerturbationType(StrEnum):
    """A kind of perturbation (gold v0 strategy, section 6)."""

    UNCITED_ABSTRACT = "uncited_abstract"
    NUMBER_CHANGE = "number_change"
    HEDGE_REMOVAL = "hedge_removal"
    METRIC_SWAP = "metric_swap"
    DIRECTION = "direction"
    CAUSAL = "causal"
    OVERGENERALISATION = "overgeneralisation"
    MISSING_COMPARATOR = "missing_comparator"

    @property
    def code(self) -> int:
        """The digit of the type in a child's item id, `G3<code><parent digits>`."""
        return list(PerturbationType).index(self) + 1

    @property
    def target_error(self) -> str:
        """The target error of the hidden record."""
        flag = self.flag
        return "unrelated_source" if flag is None else flag.value

    @property
    def flag(self) -> ScopeFlag | None:
        """The scope flag the type adds to the supporting pairs, if any."""
        return _FLAGS[self]

    @property
    def label(self) -> SourceLabel | None:
        """The pair label the type sets on the supporting pairs, or None to keep the parent's."""
        return _LABELS.get(self)

    @classmethod
    def of(cls, item: GoldItem) -> "PerturbationType | None":
        """The type of a perturbed item, from its id."""
        if item.origin is not Origin.PERTURBED or not item.item_id.startswith("G3"):
            return None
        code = int(item.item_id[2])
        return next((kind for kind in cls if kind.code == code), None)


_FLAGS: Mapping[PerturbationType, ScopeFlag | None] = {
    PerturbationType.UNCITED_ABSTRACT: None,
    PerturbationType.NUMBER_CHANGE: ScopeFlag.MAGNITUDE_MISMATCH,
    PerturbationType.HEDGE_REMOVAL: ScopeFlag.CERTAINTY_ESCALATION,
    PerturbationType.METRIC_SWAP: ScopeFlag.METRIC_MISMATCH,
    PerturbationType.DIRECTION: ScopeFlag.DIRECTION_MISMATCH,
    PerturbationType.CAUSAL: ScopeFlag.CAUSAL_OVERREACH,
    PerturbationType.OVERGENERALISATION: ScopeFlag.OVERGENERALISATION,
    PerturbationType.MISSING_COMPARATOR: ScopeFlag.MISSING_COMPARATOR,
}
_LABELS: Mapping[PerturbationType, SourceLabel] = {
    PerturbationType.UNCITED_ABSTRACT: SourceLabel.NEUTRAL,
    PerturbationType.NUMBER_CHANGE: SourceLabel.CONTRADICTS,
    PerturbationType.DIRECTION: SourceLabel.CONTRADICTS,
}


RULE_TYPES = (
    PerturbationType.UNCITED_ABSTRACT,
    PerturbationType.NUMBER_CHANGE,
    PerturbationType.HEDGE_REMOVAL,
    PerturbationType.METRIC_SWAP,
)
MODEL_TYPES = (
    PerturbationType.DIRECTION,
    PerturbationType.CAUSAL,
    PerturbationType.OVERGENERALISATION,
    PerturbationType.MISSING_COMPARATOR,
)


@dataclass(frozen=True)
class PerturbationRun:
    """The children made, and the parents skipped, by type and reason."""

    items: tuple[GoldItem, ...]
    skipped: Mapping[tuple[PerturbationType, str], int] = field(default_factory=dict)
    stopped_by_cap: bool = False

    def summary(self) -> dict[str, object]:
        """Counts only: children by type, status and domain, and skips by type and reason."""
        kinds = [PerturbationType.of(child) for child in self.items]
        skipped: dict[str, dict[str, int]] = {}
        for (kind, reason), count in sorted(
            self.skipped.items(), key=lambda entry: (entry[0][0].code, entry[0][1])
        ):
            skipped.setdefault(kind.value, {})[reason] = count
        return {
            "items": len(self.items),
            "by_type": dict(sorted(Counter(k.value for k in kinds if k).items())),
            "by_status": dict(
                sorted(Counter(c.claims[0].status.value for c in self.items).items())
            ),
            "by_domain": dict(sorted(Counter(c.domain.value for c in self.items).items())),
            "skipped": skipped,
            "stopped_by_cap": self.stopped_by_cap,
        }


class Skip(Exception):  # noqa: N818 - an internal signal with the reason a parent is skipped
    """A parent that this type cannot perturb, with the reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


def is_parent(item: GoldItem) -> bool:
    """Whether an item may be perturbed: an imported item with one `verified` claim."""
    return (
        item.origin is Origin.PUBLIC
        and len(item.claims) == 1
        and item.claims[0].status is GoldStatus.VERIFIED
    )


def _supporting(pair: GoldPair) -> bool:
    return pair.agreement_label in (SourceLabel.ENTAILS, SourceLabel.PARTIAL)


def make_child(
    parent: GoldItem,
    kind: PerturbationType,
    claim_text: str,
    pairs: Sequence[GoldPair] | None,
    confirmation: Confirmation,
) -> GoldItem:
    """The child item: the new claim, its pairs and labels, and the hidden record.

    `pairs` None keeps the parent's pairs, with the type's label on the
    supporting ones and its flag added to them.
    """
    if parent.provenance is None:
        raise ValueError(f"{parent.item_id} has no provenance")
    claim = parent.claims[0]
    item_id = f"G3{kind.code}{parent.item_id[1:]}"
    claim_id = f"{item_id}-c1"
    if pairs is None:
        changed = []
        for pair in claim.pairs:
            if _supporting(pair):
                flags = tuple(
                    dict.fromkeys((*pair.scope_flags, *([kind.flag] if kind.flag else [])))
                )
                pair = pair.model_copy(
                    update={
                        "agreement_label": kind.label or pair.agreement_label,
                        "scope_flags": flags,
                    }
                )
            changed.append(pair)
        pairs = changed
    pairs = [
        pair.model_copy(update={"pair_id": f"{claim_id}-s{n}"}) for n, pair in enumerate(pairs, 1)
    ]
    start, end = claim.span
    text_unit = parent.text_unit[:start] + claim_text + parent.text_unit[end:]
    status = guideline_status(
        [p.agreement_label.value for p in pairs], [[f.value for f in p.scope_flags] for p in pairs]
    )
    not_scored = parent.provenance.not_scored
    if kind.flag is not None:
        # A child with a flag is what S4 is scored on.
        not_scored = tuple(step for step in not_scored if step is not NotScored.S4)
    return parent.model_copy(
        update={
            "item_id": item_id,
            "origin": Origin.PERTURBED,
            "split": None,
            "text_unit": text_unit,
            "claims": (
                claim.model_copy(
                    update={
                        "claim_id": claim_id,
                        "text": claim_text,
                        "span": (start, start + len(claim_text)),
                        "pairs": tuple(pairs),
                        "status": status,
                    }
                ),
            ),
            "provenance": parent.provenance.model_copy(update={"not_scored": not_scored}),
            "hidden": PerturbationRecord(
                target_error=kind.target_error,
                secondary_errors=(),
                error_class=ErrorClass.SINGLE_ERROR,
                confirmation=confirmation,
                confirmed_by=None,
                source_item=parent.item_id,
            ),
        }
    )


def evidence_text(pair: GoldPair, texts: Mapping[str, str]) -> str:
    """The text of a pair's evidence spans, or its whole source text when it has none."""
    text = texts[pair.text_hash]
    if not pair.evidence_spans:
        return text
    return " ".join(text[span.offsets[0] : span.offsets[1]] for span in pair.evidence_spans)


# The number change --------------------------------------------------------------------


def _numbers(text: str) -> set[float]:
    return {float(match) for match in _NUMBER.findall(text)}


def _is_year(token: str) -> bool:
    return len(token) == 4 and token.isdigit() and 1900 <= int(token) <= 2099


def _fresh_number(token: str, taken: set[float]) -> str | None:
    places = len(token.split(".")[1]) if "." in token else 0
    value = float(token)
    for candidate in (value * 2, value * 3, value * 5, value * 10, value + 1, value + 7):
        text = f"{candidate:.{places}f}"
        if float(text) not in taken and float(text) != value:
            return text
    return None


def _number_change(parent: GoldItem, texts: Mapping[str, str]) -> GoldItem:
    claim = parent.claims[0]
    supporting = [pair for pair in claim.pairs if _supporting(pair)]
    in_evidence = set().union(*(_numbers(evidence_text(p, texts)) for p in supporting))
    taken = set().union(*(_numbers(texts[p.text_hash]) for p in claim.pairs))
    for match in _NUMBER.finditer(claim.text):
        token = match.group(1)
        if _is_year(token) or float(token) not in in_evidence:
            continue
        fresh = _fresh_number(token, taken)
        if fresh is None:
            raise Skip("no_fresh_number")
        text = claim.text[: match.start(1)] + fresh + claim.text[match.end(1) :]
        return make_child(
            parent, PerturbationType.NUMBER_CHANGE, text, None, Confirmation.DETERMINISTIC
        )
    raise Skip("no_number_in_evidence")


# The hedge removal ---------------------------------------------------------------------


def _hedge_removal(parent: GoldItem) -> GoldItem:
    text = parent.claims[0].text
    found = [
        match
        for hedge in HEDGES
        for match in re.finditer(rf"\b{hedge}\b,?\s*", text, flags=re.IGNORECASE)
    ]
    if not found:
        raise Skip("no_hedge")
    match = min(found, key=lambda m: m.start())
    changed = text[: match.start()] + text[match.end() :]
    changed = " ".join(changed.split())
    if match.start() == 0 and changed:
        changed = changed[0].upper() + changed[1:]
    if re.search(rf"\b{re.escape(match.group().strip(' ,'))}\b", changed, flags=re.IGNORECASE):
        raise Skip("hedge_repeated")
    return make_child(
        parent, PerturbationType.HEDGE_REMOVAL, changed, None, Confirmation.DETERMINISTIC
    )


# The metric swap -----------------------------------------------------------------------


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE) is not None


def _cased(original: str, replacement: str) -> str:
    if replacement != replacement.lower():
        return replacement
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _article(text: str, start: int, replacement: str) -> str:
    before = re.search(r"\b(a|an|A|An)\s+$", text[:start])
    if before is None:
        return text
    vowel = replacement[:1].lower() in "aeiou" or replacement[:1] in "FHLMNRSX"
    article = "an" if vowel else "a"
    if before.group(1)[0].isupper():
        article = article.capitalize()
    return text[: before.start(1)] + article + text[before.end(1) :]


def _metric_swap(parent: GoldItem, texts: Mapping[str, str]) -> GoldItem:
    claim = parent.claims[0]
    group = METRIC_GROUPS["ml" if parent.domain is Domain.ML else "biomedicine"]
    supporting = [pair for pair in claim.pairs if _supporting(pair)]
    evidence = " ".join(evidence_text(p, texts) for p in supporting)
    sources = " ".join(texts[p.text_hash] for p in claim.pairs)
    named = [metric for metric in group if _has_word(claim.text, metric)]
    if not named:
        raise Skip("no_metric")
    for metric in named:
        if not _has_word(evidence, metric):
            continue
        replacement = next(
            (other for other in group if other != metric and not _has_word(sources, other)), None
        )
        if replacement is None:
            raise Skip("no_fresh_metric")
        match = re.search(rf"\b{re.escape(metric)}\b", claim.text, flags=re.IGNORECASE)
        assert match is not None  # named above
        new = _cased(match.group(), replacement)
        text = claim.text[: match.start()] + new + claim.text[match.end() :]
        text = _article(text, match.start(), new)
        return make_child(
            parent, PerturbationType.METRIC_SWAP, text, None, Confirmation.DETERMINISTIC
        )
    raise Skip("metric_not_in_evidence")


# The uncited abstract --------------------------------------------------------------------


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


@dataclass(frozen=True)
class _Abstract:
    source_id: str
    source_group: str
    text_hash: str
    words: frozenset[str]


def _scifact_abstracts(items: Iterable[GoldItem], texts: Mapping[str, str]) -> list[_Abstract]:
    found: dict[str, _Abstract] = {}
    for item in items:
        if item.provenance is None or item.provenance.dataset is not PublicDataset.SCIFACT:
            continue
        for pair in item.claims[0].pairs:
            if pair.source_id not in found and pair.text_hash in texts:
                found[pair.source_id] = _Abstract(
                    pair.source_id,
                    pair.source_group,
                    pair.text_hash,
                    frozenset(_words(texts[pair.text_hash])),
                )
    return sorted(found.values(), key=lambda a: a.source_id)


def _uncited(parent: GoldItem, abstracts: Sequence[_Abstract]) -> GoldItem:
    claim = parent.claims[0]
    cited = {pair.source_id for pair in claim.pairs}
    words = _words(claim.text)
    scored = sorted(
        ((len(words & a.words), a) for a in abstracts if a.source_id not in cited),
        key=lambda entry: (-entry[0], entry[1].source_id),
    )
    if not scored or scored[0][0] == 0:
        raise Skip("no_similar_abstract")
    chosen = scored[0][1]
    template = claim.pairs[0]
    pair = template.model_copy(
        update={
            "source_id": chosen.source_id,
            "source_group": chosen.source_group,
            "text_hash": chosen.text_hash,
            "evidence_spans": (),
            "agreement_label": SourceLabel.NEUTRAL,
            "scope_flags": (),
        }
    )
    return make_child(
        parent, PerturbationType.UNCITED_ABSTRACT, claim.text, [pair], Confirmation.DETERMINISTIC
    )


# The run -----------------------------------------------------------------------------------


def build_rule_perturbations(
    items: Sequence[GoldItem],
    texts: Mapping[str, str],
    *,
    seed: int,
    parents: Iterable[str] | None = None,
    max_uncited: int = MAX_UNCITED,
) -> PerturbationRun:
    """Build the four rule-made types from every `verified` parent, in a fixed order.

    `parents` limits the parents to these item ids, such as the v0 sample's.
    The uncited abstract is made only from SciFact parents, in an order
    shuffled by `seed`, and at most `max_uncited` times.
    """
    allowed = None if parents is None else set(parents)
    candidates = sorted(
        (i for i in items if is_parent(i) and (allowed is None or i.item_id in allowed)),
        key=lambda i: i.item_id,
    )
    children: list[GoldItem] = []
    skipped: Counter[tuple[PerturbationType, str]] = Counter()

    def attempt(kind: PerturbationType, build: Callable[[], GoldItem]) -> bool:
        try:
            children.append(build())
        except Skip as skip:
            skipped[(kind, skip.reason)] += 1
            return False
        return True

    for parent in candidates:
        attempt(PerturbationType.NUMBER_CHANGE, partial(_number_change, parent, texts))
        attempt(PerturbationType.HEDGE_REMOVAL, partial(_hedge_removal, parent))
        attempt(PerturbationType.METRIC_SWAP, partial(_metric_swap, parent, texts))
    scifact = [
        p
        for p in candidates
        if p.provenance is not None and p.provenance.dataset is PublicDataset.SCIFACT
    ]
    random.Random(seed).shuffle(scifact)
    abstracts = _scifact_abstracts(items, texts)
    made = 0
    for parent in scifact:
        if made >= max_uncited:
            skipped[(PerturbationType.UNCITED_ABSTRACT, "cap_reached")] += 1
        elif attempt(PerturbationType.UNCITED_ABSTRACT, partial(_uncited, parent, abstracts)):
            made += 1
    return PerturbationRun(tuple(sorted(children, key=lambda c: c.item_id)), dict(skipped))
